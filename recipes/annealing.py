# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Chrome OS annealing builders.

The annealing builders run in serial and do the following:

1. Checkout ToT
2. Rewind (i.e. checkout an ancestor) projects with missing dependencies; this
   prevents a bad tree state due to e.g. Gerrit replication latency.
3. Uprev portage packages (for each board)
4. Make a manifest snapshot (aka "revlocked manifest"), and push it
5. Perform post-submit tasks like:
  * push metadata for e.g. Goldeneye, findit
"""

import collections
import urlparse

from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromite.api.packages import UprevPackagesRequest
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.annealing import AnnealingProperties
from PB.recipes.chromeos.annealing import SnapshotGerritChanges

from google.protobuf import json_format

from recipe_engine import util

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/isolated',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'depends',
    'easy',
    'gerrit',
    'git',
    'git_footers',
    'git_txn',
    'naming',
    'portage',
    'repo',
]


PROPERTIES = AnnealingProperties


def RunSteps(api, properties):
  manifest_ref = properties.manifest_ref
  if not manifest_ref:
    raise ValueError('must set manifest ref')

  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.context(
        cwd=api.cros_source.workspace_path.join('manifest-internal')):
      snapshot_xml = api.repo.manifest_snapshot()
      manifest_diffs = api.repo.diff_remote_and_local_manifests(
          api.cros_source.INTERNAL_MANIFEST_URL, manifest_ref, snapshot_xml)

      # TODO(athilenius): It would be nice to set the 'Info' column here.
      gerrit_commits = []
      if manifest_diffs is not None:
        # If there are zero diffs (empty array) then there is nothing
        # interesting to be done.
        if len(manifest_diffs) == 0:
          return

        # Otherwise we need to ensure all of those diffs have fulfilled deps.
        api.depends.ensure_manifest_cq_depends_fulfilled(manifest_diffs)

        # Then, record the diffs. We are specifically interested in what
        # gerrit changes have landed.
        gerrit_commits = record_gerrit_changes(api, manifest_diffs)

      with api.step.nest('publish snapshot') as step:
        snapshot_repo_url = api.cros_source.INTERNAL_MANIFEST_URL
        api.git.fetch_ref(snapshot_repo_url, manifest_ref)
        api.git.checkout('FETCH_HEAD')
        snapshot_commit_message = make_message(
            api, manifest_ref, gerrit_commits,
            properties.disable_gerrit_commits_in_commit_message)
        api.git_txn.update_ref_write_file(
            snapshot_repo_url, manifest_ref, snapshot_commit_message,
            api.cros_source.workspace_path.join('manifest-internal/snapshot.xml'),
            snapshot_xml)

        # Use the newly created snapshot commit as the build output.
        snapshot_commit = make_gitiles_commit(api, snapshot_repo_url,
                                              api.git.head_commit())
        api.buildbucket.set_output_gitiles_commit(snapshot_commit)

    # It may seem weird that we publish uprevs after publishing the snapshot.
    # Unfortunately, publishing uprevs takes ~10 minutes, in which time it is
    # not unlikely that commits will land upstream and be trivially merged by
    # Gerrit. This means the local uprev commits will have different sha1s
    # from the remote uprev commits. The only two ways around it are (a)
    # run repo sync a second time, after uprevs, or (b) include the uprevs
    # in the NEXT snapshot. We choose the least wasteful option.
    with api.step.nest('uprev packages'), api.context(
        cwd=api.cros_source.workspace_path):
      request = UprevPackagesRequest(chroot=api.cros_sdk.chroot,
                                     overlay_type=OVERLAYTYPE_BOTH)
      response = api.cros_build_api.PackageService.Uprev(request)

      ebuilds_by_repository = collections.defaultdict(list)
      for ebuild in response.modified_ebuilds:
        with api.context(
              cwd=api.path.abs_to_path(api.path.dirname(ebuild.path))):
          repository = api.git.repository_root()
          ebuilds_by_repository[repository].append(ebuild.path)

      with api.step.nest('commit uprevs'):
        for repository, ebuilds in ebuilds_by_repository.iteritems():
          with api.context(cwd=api.path.abs_to_path(repository)):
            api.git.add(ebuilds)
            api.git.commit_files(ebuilds, 'Marking set of ebuilds as stable')

      with api.step.nest('push uprevs'):
        push = util.exponential_retry(retries=3)(api.git.push)
        for repository, ebuilds in ebuilds_by_repository.iteritems():
          with api.context(cwd=api.path.abs_to_path(repository)):
            # Filter to ebuilds that exist. In particular, we need to exclude
            # the version of the ebuild from prior to the uprev.
            existing_ebuilds = []
            for ebuild in ebuilds:
              api.path.mock_add_paths(ebuild)
              if api.path.exists(ebuild):
                existing_ebuilds.append(ebuild)
            projects = api.repo.project_infos(projects=existing_ebuilds)
            assert len(projects) == 1, 'expected 1 project, got: %r' % projects
            project = projects[0]
            push(project.remote, 'HEAD:' + project.branch,
                 dry_run=not properties.publish_uprevs)

    if properties.child_builders:
      with api.step.nest('schedule child builds'):
        requests = [
            api.buildbucket.schedule_request(gitiles_commit=snapshot_commit,
                                             builder=child, bucket='postsubmit')
            for child in properties.child_builders
        ]
        api.buildbucket.schedule(requests)


def record_gerrit_changes(api, manifest_diffs):
  """Find all Gerrit changes that landed since the last snapshot.

  Args:
    * api (object): See RunSteps documentation.
    * manifest_diffs (list[ManifestDiff]): Diffs from ToT to last snapshot.

  Returns:
    list[Commit]: The Gerrit-reviewed commits since the last snapshot.
  """
  with api.step.nest('record new gerrit changes'):
    gerrit_changes = []
    gerrit_commits = []
    for diff in manifest_diffs:
      with api.step.nest(diff.path) as step, api.context(
          cwd=api.cros_source.workspace_path.join(diff.path)):
        commits = api.git.log(diff.from_rev, diff.to_rev, limit=30)
        for commit in commits:
          reviewed_on_footers = api.git_footers.from_message(commit.message,
                                                             key='Reviewed-on')
          if reviewed_on_footers:
            gerrit_change_url = reviewed_on_footers[0]
            gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
            gerrit_change.project = gerrit_change.project or diff.name
            gerrit_change_title = api.naming.get_commit_title(commit)
            step.presentation.links[gerrit_change_title] = gerrit_change_url
            gerrit_changes.append(gerrit_change)
            gerrit_commits.append(commit)

    output_dir = api.path.mkdtemp(prefix='snapshot-gerrit-changes-')
    output_file = output_dir.join('snapshot_gerrit_changes.json')
    output_proto = SnapshotGerritChanges(gerrit_changes=gerrit_changes)
    output_json = json_format.MessageToJson(output_proto)
    api.file.write_raw('write gerrit changes json', output_file, output_json)

    isolated = api.isolated.isolated(output_dir)
    isolated.add_file(output_file)
    # TODO(evanhernandez): Re-enable upload after isolated is fixed.
    isolated_hash = None
    # isolated_hash = isolated.archive('upload gerrit changes to isolate')

    api.easy.set_property_step('snapshot_gerrit_changes', isolated_hash,
                               step_name='output isolate id')

    # TODO(evanhernandez): Storing/returning these commits is a stain.
    # Stop this once the Milo blame list accepts Gerrit changes as input.
    return gerrit_commits


def make_gitiles_commit(api, repo_url, commit_id):
  """Create a GitilesCommit for the given |repo_url| and |commit_id|."""
  url = urlparse.urlparse(repo_url)
  return common_pb2.GitilesCommit(
      host=url.hostname,
      project=url.path[1:], # strip leading /
      ref='refs/heads/master',
      id=commit_id,
  )

def make_message(api, manifest_ref, gerrit_commits, disable_gerrit_commits):
  """Creates and returns the commit message with a Cr-Commit-Position.

  Creates and returns the commit message with a Cr-Commit-Position
  suitable for use by FindIt, as in:

  Cr-Commit-Position: refs/heads/snapshot@{#%d}

  Also appends the commit messages for all Gerrit changes since the last
  snapshot.

  Args:
    * api (object): See RunSteps documentation.
    * manifest_ref (str): The git reference to use in the commit message.
    * gerrit_commits (list[Commit]): List of Gerrit-pushed commits since the
        last snapshot.
    * disable_gerrit_commits (bool): If true, gerrit_commits will not be written
        in the message.

  Returns:
    A string containing the commit message.
  """
  with api.step.nest('create snapshot commit message'):
    position = api.git_footers.position_num('HEAD') + 1
    lines = ['annealing manifest snapshot %d' % position]

    if disable_gerrit_commits:
      lines.append('**** Writing Gerrit Changes Disabled ****')
    elif gerrit_commits:
      lines.append('************ Gerrit Changes ************')
      lines.append('\n\n----------------------------------------\n\n'.join(
          commit.message for commit in gerrit_commits))
      lines.append('****************************************')
    else:
      lines.append('********* No New Gerrit Changes *********')

    lines.append('Cr-Commit-Position: refs/heads/%s@{#%d}' % (manifest_ref,
                                                              position))

    return '\n\n'.join(lines)


def GenTests(api):
  yield (api.test('basic') + #
         api.properties(AnnealingProperties(manifest_ref='snapshot')))

  yield (
      api.test('has-manifest-change') +  #
      api.properties(AnnealingProperties(manifest_ref='snapshot')) +  #
      api.properties(
          AnnealingProperties(child_builders=['eve-postsubmit'])) +  #
      api.step_data(
          'repo manifest', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="TO_REV" /></manifest>'))
      +  #
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )) +  #
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers',
          api.gerrit.test_gerrit_change_url()))

  yield (
      api.test('no-gerrit-change') +  #
      api.properties(AnnealingProperties(manifest_ref='snapshot')) +  #
      api.step_data(
          'repo manifest', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="TO_REV" /></manifest>'))
      +  #
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )) + #
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''))

  yield (
      api.test('disable-commits-in-commit-message') +  #
      api.properties(AnnealingProperties(
          manifest_ref='snapshot',
          disable_gerrit_commits_in_commit_message=True)) +  #
      api.step_data(
          'repo manifest', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="TO_REV" /></manifest>'))
      +  #
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )) + #
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers',
          api.gerrit.test_gerrit_change_url()))

  yield (api.test('missing required properties') +  #
         api.properties(AnnealingProperties()) + #
         api.expect_exception('ValueError'))
