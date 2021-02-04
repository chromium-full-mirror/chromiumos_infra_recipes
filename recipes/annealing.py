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

from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.annealing import AnnealingProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from recipe_engine import util

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_build_api',
    'cros_cq_depends',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'cros_tags',
    'easy',
    'gerrit',
    'git',
    'git_footers',
    'git_txn',
    'naming',
    'repo',
    'src_state',
]

PROPERTIES = AnnealingProperties


def RunSteps(api, properties):
  # If we're configured not to publish uprev's run as staging.
  is_staging = not properties.publish_uprevs
  workspace_path = api.src_state.workspace_path

  commit = api.src_state.gitiles_commit
  prior_internal = prior_external = None

  manifest_ref = properties.manifest_ref
  if not manifest_ref:
    raise ValueError('must set manifest ref')

  with api.cros_source.checkout_overlays_context():
    internal_manifest = api.src_state.internal_manifest
    external_manifest = api.src_state.external_manifest

    # Do this before anything else.  Most notably, if it is called while in
    # internal_manifest.path, HEAD stops tracking the lowerdir in the overlayfs,
    # which means we fail when the cache updates manifest-internal.  See
    # crbug/1148052.
    api.cros_source.ensure_synced_cache(is_staging=is_staging)

    with api.context(cwd=internal_manifest.path):
      if api.cq.state == api.cq.INACTIVE:
        api.cros_source.checkout_tip_of_tree()

      if api.cq.state != api.cq.INACTIVE and not commit.id:
        # CQ run, but no commit given.  Grab the most recent |manifest_ref|.
        ref = commit.ref or 'refs/heads/{}'.format(manifest_ref)
        commit.host = commit.host or api.src_state.internal_manifest.host
        commit.project = commit.project or internal_manifest.project
        commit.ref = ref
        commit.id = api.git.fetch_ref(internal_manifest.url, ref)

      if commit.id:
        with api.step.nest('recreating older run'):
          properties.dry_run = True
          # Check out the gitiles_commit we received, and declare the prior
          # commit in each manifest to be the prior commit. Start by forcing a
          # checkout on the right branch.
          branch = (
              commit.ref[len('refs/heads/'):]
              if commit.ref.startswith('refs/heads/') else commit.ref)
          api.cros_source.ensure_synced_cache(
              cache_path_override=workspace_path, is_staging=is_staging,
              init_opts=dict(manifest_branch=branch))
          api.cros_source.sync_snapshot(commit)
          prior_internal = api.git.fetch_refs(internal_manifest.url, commit.id,
                                              count=2)[-1]
          test_data = api.git_footers.test_api.step_test_data_factory('e' * 40)
          footers = api.git_footers.from_ref(commit.id,
                                             key='Cr-External-Snapshot',
                                             step_test_data=test_data)
          if not footers:
            raise StepFailure('missing Cr-External-Snapshot footer')
          prior_external = footers[0] if footers else None
          with api.context(cwd=workspace_path):
            api.repo.init(internal_manifest.url,
                          manifest_branch=internal_manifest.branch)

      prior_internal = prior_internal or api.git.fetch_ref(
          internal_manifest.url, manifest_ref)

      with api.context(cwd=external_manifest.path):
        prior_external = prior_external or api.git.fetch_ref(
            external_manifest.url, manifest_ref)

        # Sync mirrored manifest files from manifest-internal to manifest.
        with api.step.nest('sync manifests') as presentation:
          presentation.logs['prior versions'] = [
              'internal {}: {}'.format(manifest_ref, prior_internal),
              'external {}: {}'.format(manifest_ref, prior_external),
          ]

          def _update_callback():
            """Callback function for git_txn to update mirrored files."""
            files = api.cros_source.mirrored_manifest_files
            external_paths = [external_manifest.path.join(p) for p in files]
            for path in files:
              api.file.copy('Copy manifest-internal/{}'.format(path),
                            internal_manifest.path.join(path),
                            external_manifest.path.join(path))
            if not any(api.git.diff_check(f) for f in external_paths):
              return False
            if properties.dry_run or is_staging:
              presentation.logs['skip'] = ['staging/dry-run: skipping sync']
              properties.dry_run = True
              api.step('git reset', ['git', 'reset', '--hard'])
              return False
            commit_message = 'Syncing with internal manifest.'
            api.git.add(external_paths)
            api.git.commit(commit_message)

          if not api.git_txn.update_ref(external_manifest.url,
                                        _update_callback):
            presentation.step_text = 'No diffs'

        api.easy.set_properties_step(dry_run=properties.dry_run)

        prior_external = (
            manifest_ref if properties.use_ref_not_id else prior_external)
        prior_internal = (
            manifest_ref if properties.use_ref_not_id else prior_internal)
        # Generate a public snapshot of the manifest in the manifest/ repo.  We
        # need to do this _first_ so that we can fill in the
        # Cr-External-Snapshot footer in in the internal snapshot commit.
        external_snapshot_ref = None
        # Generate the manifest from public repo
        snapshot_xml_extern = api.repo.manifest(
            external_manifest.path.join('default.xml'), pinned=True,
            step_name='generate external manifest')

        # Generate Cr-Snapshot-Identifer (b/171751551).
        with api.step.nest('fetch previous snapshot identifier'):
          api.git.fetch_ref(internal_manifest.url, prior_internal)
          test_data = api.git_footers.test_api.step_test_data_factory('1000000')
          snapshot_identifier_footers = api.git_footers.from_ref(
              "FETCH_HEAD", key='Cr-Snapshot-Identifier',
              step_test_data=test_data)
          if not snapshot_identifier_footers:
            raise StepFailure('missing Cr-Snapshot-Identifier footer')
          snapshot_identifier = int(snapshot_identifier_footers[0])
          snapshot_identifier += 1

        # And publish.
        with api.step.nest('publish external snapshot'):
          external_snapshot_commit = _publish_snapshot(
              api, external_manifest.url, manifest_ref, prior_external,
              external_manifest.path.join('snapshot.xml'), snapshot_xml_extern,
              disable_gerrit=True, dry_run=properties.dry_run,
              footers=[("Cr-Snapshot-Identifier", str(snapshot_identifier))])
          external_snapshot_ref = external_snapshot_commit.id

      # snapshot internal manifest
      snapshot_xml_intern = api.repo.manifest(
          pinned=True, step_name='generate internal manifest')
      manifest_diffs = api.repo.diff_remote_and_local_manifests(
          internal_manifest.url, manifest_ref, snapshot_xml_intern)

      # TODO(athilenius): It would be nice to set the 'Info' column here.
      gerrit_commits = []
      if manifest_diffs is not None:
        # If there are zero diffs (empty array) then there is nothing
        # interesting to be done.
        if len(manifest_diffs) == 0:
          return

        # Make sure that we have not lost commits.  If the new revision at a
        # path is older than the prior one, provide a clearer failure message
        # than the one we get in cros_cq_depends.
        # See b/176121817 and ci.chromium.org/b/8860265036779649984.
        # TODO(crbug/1169277): If the change is in a pinned entry in the
        # manifest, ignore the downrev.  Once that is happening, drop
        # properties.ignore_downrev_paths.
        with api.step.nest('check reachability') as reach_pres:
          downrevs = []
          for diff in manifest_diffs:
            with api.context(cwd=workspace_path.join(diff.path)):
              if (not api.git.is_reachable(diff.from_rev, diff.to_rev) and
                  diff.path not in properties.ignore_downrev_paths):
                downrevs.append('{}: {} is not an ancestor of {}'.format(
                    diff.path, diff.from_rev, diff.to_rev))

          if downrevs:
            # TODO(crbug/1169277): Add code to distinguish these cases, and make
            # the error only apply to case #1.
            # There are 3 cases that can lead to an unreachable prior version:
            # 1. Commits were lost from the git repo.  (bug).
            # 2. A pinned-entry in the manifest has a change that reverts an
            #    uprev in that repo.  (not a bug)
            # 3. A manifest entry changes branches. (not a bug)
            # Of the set, #1 is generally the least likely to occur, so this is
            # a warning (which is ignored by LUCI/Milo) for now.
            reach_pres.logs['downrevs'] = downrevs
            reach_pres.step_text = 'some downrevs occurred'

        # Otherwise we need to ensure all of those diffs have fulfilled deps.
        api.cros_cq_depends.ensure_manifest_cq_depends_fulfilled(manifest_diffs)

        # Then, get the diffs. We are specifically interested in what
        # gerrit changes have landed.
        gerrit_commits, jobs = _get_gerrit_changes(api, manifest_diffs,
                                                   properties.path_triggers)

      with api.step.nest('publish internal snapshot'):
        internal_snapshot_commit = _publish_snapshot(
            api, internal_manifest.url, manifest_ref, prior_internal,
            internal_manifest.path.join('snapshot.xml'), snapshot_xml_intern,
            gerrit_commits, properties.disable_gerrit_commits_in_commit_message,
            footers=[("Cr-External-Snapshot", external_snapshot_ref),
                     ("Cr-Snapshot-Identifier", str(snapshot_identifier))],
            dry_run=properties.dry_run)

        # Set output.properties.commit, this will also set the commit as the
        # build output.
        api.src_state.gitiles_commit = internal_snapshot_commit

      if jobs and not properties.dry_run:
        _schedule_triggered_builds(api, internal_snapshot_commit, jobs)

      # It may seem weird that we publish uprevs after publishing the snapshot.
      # Unfortunately, publishing uprevs takes ~10 minutes, in which time it is
      # not unlikely that commits will land upstream and be trivially merged by
      # Gerrit. This means the local uprev commits will have different sha1s
      # from the remote uprev commits. The only two ways around it are (a)
      # run repo sync a second time, after uprevs, or (b) include the uprevs
      # in the NEXT snapshot. We choose the least wasteful option.
      with api.step.nest('uprev packages'), api.context(cwd=workspace_path):
        response = api.cros_sdk.uprev_packages(name='uprev ebuilds')

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
              api.git.commit('Marking set of ebuilds as stable', files=ebuilds)

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
              # The list of projects should be checked to see if all elements
              # are equivalent. This check is temporarily removed because
              # Annealing is broken, and length isn't the right thing to check.
              # assert len(projects) == 1, \
              #     'expected 1 project, got: %r' % projects
              project = projects[0]
              push(project.remote,
                   'HEAD:refs/for/' + project.branch + '%notify=NONE,submit',
                   dry_run=is_staging or properties.dry_run)


def _schedule_triggered_builds(api, commit, jobs):
  """Schedule any triggered jobs.

  Args:
    jobs: list(PathTrigger.Job) to be launched.
  """
  props = api.cros_infra_config.props_for_child_build
  requests = []
  for job in jobs:
    requests.append(
        api.buildbucket.schedule_request(
            project=job.project or api.buildbucket.build.builder.project,
            bucket=job.bucket or api.buildbucket.build.builder.bucket,
            builder=job.builder, gitiles_commit=commit, properties=props))
  api.buildbucket.schedule(requests, url_title_fn=api.naming.get_build_title,
                           step_name='schedule triggered builds')


def _publish_snapshot(api, repo_url, snapshot_ref, prior_commit, snapshot_file,
                      snapshot_xml, gerrit_commits=None, disable_gerrit=False,
                      footers=None, dry_run=False):
  """Generate snapshot.xml file and commit it to a ref.

  Does not call api.context() so the cwd should be set to the appropriate
  path in the workspace for a git fetch to work.

  Args:
      api (object):   See RunSteps documentation
      repo_url:       URL to git repo to publish snapshot.xml file to
      snapshot_ref:   git ref to publish to (e.g.: "snapshot")
      prior_commit:   The prior commit ID.
      snapshot_file:  location of snapshot.xml to write
      snapshot_xml:   contents to write to snapshot.xml in cwd
      gerrit_commits: List of gerrit commits to reference in commit message
      disable_gerrit: If True, disable gerrit commits in commit message
      footers:        List of (key,value) pairs to add as footers
      dry_run:        Whether this is a dry run.

  Returns:
      GitilesCommit object representing the new commit.
  """
  footers = footers or []
  gerrit_commits = gerrit_commits or []

  # fetch and update the ref with the new snapshot file
  api.git.fetch_ref(repo_url, prior_commit)

  with api.git.head_context():
    api.git.checkout('FETCH_HEAD')
    commit_message = _make_message(api, snapshot_ref, gerrit_commits,
                                   disable_gerrit)

    if footers:
      commit_message += "\n"
      for key, val in footers:
        commit_message += "%s: %s\n" % (key, val)

    if not dry_run:
      api.git_txn.update_ref_write_file(repo_url, commit_message, snapshot_file,
                                        snapshot_xml, ref=snapshot_ref)
    return _make_gitiles_commit(api, repo_url, 'refs/heads/%s' % snapshot_ref,
                                api.git.head_commit())


def _get_gerrit_changes(api, manifest_diffs, path_triggers=None):
  """Find all Gerrit changes that landed since the last snapshot.

  Args:
    * api (object): See RunSteps documentation.
    * manifest_diffs (list[ManifestDiff]): Diffs from ToT to last snapshot.
    * path_triggers (list[PathTrigger]): Paths that trigger jobs.

  Returns:
    tuple(
      list[Commit]: The Gerrit-reviewed commits since the last snapshot,
      list[PathTrigger.Job]: List of jobs to trigger when done.)
  """
  jobs = []
  with api.step.nest('record new gerrit changes'):
    gerrit_changes = []
    gerrit_commits = []
    for diff in manifest_diffs:
      with api.step.nest(diff.path) as step, api.context(
          cwd=api.src_state.workspace_path.join(diff.path)):
        commits = api.git.log(diff.from_rev, diff.to_rev, limit=30)
        for commit in commits:
          reviewed_on_footers = api.git_footers.from_message(
              commit.message, key='Reviewed-on')
          if reviewed_on_footers:
            gerrit_change_url = reviewed_on_footers[0]
            gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
            gerrit_change.project = gerrit_change.project or diff.name
            gerrit_change_title = api.naming.get_commit_title(commit)
            step.presentation.links[gerrit_change_title] = gerrit_change_url
            gerrit_changes.append(gerrit_change)
            gerrit_commits.append(commit)
        # See if we hit any triggers.
        for trigger in path_triggers or []:
          if (diff.path == trigger.repo_path and
              (not trigger.file_paths or
               api.git.log(diff.from_rev, diff.to_rev, limit=1,
                           paths=trigger.file_paths))):
            jobs.extend(trigger.jobs)

    # TODO(evanhernandez): Storing/returning these commits is a stain.
    # Stop this once the Milo blame list accepts Gerrit changes as input.
    return gerrit_commits, jobs


def _make_gitiles_commit(_api, repo_url, ref, commit_id):
  """Create a GitilesCommit for the given |repo_url|, |ref|, and |commit_id|."""
  url = urlparse.urlparse(repo_url)
  return common_pb2.GitilesCommit(
      host=url.hostname,
      project=url.path[1:], # strip leading /
      ref=ref,
      id=commit_id,
  )


def _make_message(api, manifest_ref, gerrit_commits, disable_gerrit_commits):
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
  with api.step.nest('create commit message'):
    position = api.git_footers.position_num('HEAD') + 1
    lines = ['annealing manifest %s %d' % (manifest_ref, position)]

    if disable_gerrit_commits:
      lines.append('**** Writing Gerrit Changes Disabled ****')
    elif gerrit_commits:
      lines.append('************ Gerrit Changes ************')
      lines.append('\n\n----------------------------------------\n\n'.join(
          commit.message for commit in gerrit_commits))
      lines.append('****************************************')
    else:
      lines.append('********* No New Gerrit Changes *********')

    lines.append('Cr-Commit-Position: refs/heads/%s@{#%d}' %
                 (manifest_ref, position))

    return '\n\n'.join(lines)


def GenTests(api):

  yield api.test(
      'basic',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
  )

  yield api.test(
      'no-snapshot-identifier',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.git_footers.step_data(
          'fetch previous snapshot identifier.read git footers', ''),
  )

  yield api.test(
      'snapshot-manifest-has-manifest-change',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers',
          api.gerrit.test_gerrit_change_url()),
  )

  yield api.test(
      'snapshot-manifest-has-manifest-change-that-triggers',
      api.properties(
          AnnealingProperties(
              manifest_ref='snapshot', path_triggers=[
                  AnnealingProperties.PathTrigger(
                      repo_path='NAME', file_paths=['dir/package/pkg*.ebuild'],
                      jobs=[
                          AnnealingProperties.PathTrigger.Job(
                              builder='triggered-build')
                      ])
              ])),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers',
          api.gerrit.test_gerrit_change_url()),
  )

  yield api.test(
      'sync-manifests-has-manifest-change',
      api.properties(
          AnnealingProperties(manifest_ref='main', publish_uprevs=True)),
      api.git.diff_check(True),
  )

  yield api.test(
      'staging-sync-manifests-has-manifest-change',
      api.properties(AnnealingProperties(manifest_ref='main')),
      api.git.diff_check(True),
  )

  # No changes in the manifest at all.
  yield api.test(
      'no-change',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="FROM_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="FROM_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.post_check(post_process.DoesNotRun, 'record new gerrit changes'),
      api.post_check(post_process.DoesNotRun, 'publish internal snapshot'),
  )

  # Manifest changes, but no gerrit change to go with it.
  yield api.test(
      'no-gerrit-change',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
  )

  # Dry Run: manifest changes, but no gerrit change to go with it.
  yield api.test(
      'dry-run',
      api.properties(
          AnnealingProperties(manifest_ref='snapshot', dry_run=True)),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
  )

  # CQ: manifest changes, but no gerrit change to go with it.
  yield api.test(
      'cq-build',
      api.buildbucket.ci_build(project='chromeos',
                               git_repo=api.src_state.internal_manifest.url,
                               git_ref='refs/heads/snapshot'),
      api.cq(full_run=True),
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
  )

  yield api.test(
      'cq-build-no-footer',
      api.buildbucket.ci_build(project='chromeos',
                               git_repo=api.src_state.internal_manifest.url,
                               git_ref='refs/heads/snapshot'),
      api.cq(full_run=True),
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data('recreating older run.read git footers',
                    stdout=api.raw_io.output('')),
      api.post_check(post_process.StatusFailure),
      api.post_check(post_process.DoesNotRun, 'record new gerrit changes'),
      api.post_check(post_process.DoesNotRun, 'publish internal snapshot'),
  )

  # CQ without bb commit: manifest changes, but no gerrit change to go with it.
  yield api.test(
      'cq-build-no-commit',
      api.cq(full_run=True),
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
  )

  yield api.test(
      'only-ignored-gerrit-change',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '<project name="SNAP" revision="TO_REV"><annotation '
              'name="snapshot-mode" value="ignore-diff"/></project>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="TO_REV" />'
              '<project name="SNAP" revision="FROM_REV"><annotation '
              'name="snapshot-mode" value="ignore-diff"/></project>'
              '</manifest>')),
      api.post_check(post_process.DoesNotRun, 'record new gerrit changes'),
      api.post_check(post_process.DoesNotRun, 'publish internal snapshot'),
  )

  yield api.test(
      'disable-commits-in-commit-message',
      api.properties(
          AnnealingProperties(manifest_ref='snapshot',
                              disable_gerrit_commits_in_commit_message=True)),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers',
          api.gerrit.test_gerrit_change_url()),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
  )

  yield api.test(
      'missing-required-properties',
      api.properties(AnnealingProperties()),
      api.expect_exception('ValueError'),
  )

  # TODO(crbug/1169277) this will become multiple tests.
  yield api.test(
      'downrev',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.step_data('check reachability.git merge-base', retcode=1),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'crbug-1169277-ignored-downrev',
      api.properties(
          AnnealingProperties(manifest_ref='snapshot',
                              ignore_downrev_paths=['NAME'])),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output('<manifest visibility="external">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output('<manifest visibility="internal">'
                                   '<project name="NAME" revision="TO_REV"/>'
                                   '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.step_data('check reachability.git merge-base', retcode=1),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
      api.post_check(post_process.StatusSuccess),
  )
