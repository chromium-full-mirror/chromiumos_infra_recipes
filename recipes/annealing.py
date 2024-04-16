# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the CrOS annealing builders.

The annealing builders run in serial and do the following:

1. Checkout ToT
2. Rewind (i.e. checkout an ancestor) projects with missing dependencies; this
   prevents a bad tree state due to e.g. Gerrit replication latency.
3. Uprev portage packages (for each board)
4. Make a manifest snapshot (aka "pinned manifest"), and push it
5. Perform post-submit tasks like:
  * push metadata for e.g. Goldeneye, findit
"""

import base64
import collections
import json
import urllib
from xml.etree import cElementTree as ElementTree
import zlib

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipes.chromeos.annealing import AnnealingProperties
from PB.chromite.api.packages import RevBumpChromeRequest

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cv',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'binhost_lookup_service',
    'cros_build_api',
    'cros_cq_depends',
    'cros_infra_config',
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
  commit = api.src_state.gitiles_commit
  cq_run = api.cv.active
  # If we have a commit.ref, then this must be a CQ run.
  assert cq_run or not commit.ref, 'GitilesCommit provided for non-CQ run'

  # If this is not a CQ run, we need to sync tip-of-tree.  If it is, then we
  # should sync to the provided commit, or snapshot if none was provided.
  api.cros_source.configure_builder(default_main=not cq_run)

  # If we're configured not to publish uprev's run as staging.
  is_staging = not properties.publish_uprevs
  workspace_path = api.src_state.workspace_path
  prior_internal = prior_external = diffs = None
  dry_run = api.cv.active or properties.dry_run
  manifest_ref = properties.manifest_ref
  if not manifest_ref:
    raise StepFailure('must set manifest ref')

  with api.cros_source.checkout_overlays_context(disk_type='pd-ssd'):
    internal_manifest = api.src_state.internal_manifest
    external_manifest = api.src_state.external_manifest

    # Do this before anything else.  Most notably, if it is called while in
    # internal_manifest.path, HEAD stops tracking the lowerdir in the overlayfs,
    # which means we fail when the cache updates manifest-internal.  See
    # crbug/1148052.
    api.cros_source.ensure_synced_cache(is_staging=is_staging)

    with api.context(cwd=internal_manifest.path):
      if not api.cv.active:
        api.cros_source.checkout_tip_of_tree()

      if api.cv.active and not commit.id:
        # CQ run, but no commit given.  Grab the most recent |manifest_ref|.
        # This may be different from a provided GitilesCommit, but that is OK.
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
              init_opts={'manifest_branch': branch})
          api.cros_source.sync_to_gitiles_commit(commit)
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
        diffs = _sync_manifest(api, properties, manifest_ref, prior_internal,
                               prior_external, internal_manifest,
                               external_manifest)

        # One or more uprevs did not complete, end recipe and
        # do not generate snapshot
        if not _uprev_packages(api, properties, workspace_path, diffs, dry_run):
          raise StepFailure('Failed to uprev all changes')

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
        # TODO(b/315001529): build shouldn't need this forever.
        snapshot_xml_extern = _remove_notice_node(
            api,
            snapshot_xml_extern,
            step_name='remove <notice> from external manifest',
        )

      # snapshot internal manifest
      snapshot_xml_intern = api.repo.manifest(
          pinned=True, step_name='generate internal manifest')
      # TODO(b/315001529): build shouldn't need this forever.
      snapshot_xml_intern = _remove_notice_node(
          api,
          snapshot_xml_intern,
          step_name='remove <notice> from internal manifest',
      )
      manifest_diffs = api.repo.diff_remote_and_local_manifests(
          internal_manifest.url, manifest_ref, snapshot_xml_intern,
          use_merge_base=True)

      # TODO(athilenius): It would be nice to set the 'Info' column here.
      gerrit_commits = []
      if manifest_diffs is not None:
        # If there are zero diffs (empty array) then there is nothing
        # interesting to be done.
        if len(manifest_diffs) == 0:
          return

        # Pushing to staging-infra-{$BRANCH} may fail since the commit histories
        # have different acestors. If we can verify that they are reachable
        # through a prior commit we will ignore the CQ depends.
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
              if (not api.git.is_reachable(diff.from_rev) and
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
        try:
          api.cros_cq_depends.ensure_manifest_cq_depends_fulfilled(
              manifest_diffs)
        except StepFailure:
          if not properties.ignore_cq_depends_failure:
            raise

        # Then, get the diffs. We are specifically interested in what
        # gerrit changes have landed.
        gerrit_commits = _get_gerrit_changes(api, manifest_diffs)

      # Generate Cr-Snapshot-Identifer (b/171751551).
      with api.step.nest('fetch previous snapshot identifier'):
        api.git.fetch_ref(internal_manifest.url, prior_internal)
        test_data = api.git_footers.test_api.step_test_data_factory('1000000')
        snapshot_identifier_footers = api.git_footers.from_ref(
            'FETCH_HEAD', key='Cr-Snapshot-Identifier',
            step_test_data=test_data)
        if not snapshot_identifier_footers:
          raise StepFailure('missing Cr-Snapshot-Identifier footer')
        snapshot_identifier = int(snapshot_identifier_footers[0])
        snapshot_identifier += 1

      # And publish.
      with api.step.nest('publish external snapshot'), \
          api.context(cwd=external_manifest.path):
        external_snapshot_commit = _publish_snapshot(
            api, external_manifest.url, manifest_ref, prior_external,
            external_manifest.path.join('snapshot.xml'), snapshot_xml_extern,
            disable_gerrit=True, dry_run=dry_run,
            footers=[('Cr-Snapshot-Identifier', str(snapshot_identifier))])
        external_snapshot_ref = external_snapshot_commit.id
        # Add snapshot commit id to tags so that they can be queried for.
        api.cros_tags.add_tags_to_current_build(
            **{'published_snapshot_id': external_snapshot_commit.id})

      with api.step.nest('publish internal snapshot'):
        internal_snapshot_commit = _publish_snapshot(
            api, internal_manifest.url, manifest_ref, prior_internal,
            internal_manifest.path.join('snapshot.xml'), snapshot_xml_intern,
            gerrit_commits, properties.disable_gerrit_commits_in_commit_message,
            footers=[('Cr-External-Snapshot', external_snapshot_ref),
                     ('Cr-Snapshot-Identifier', str(snapshot_identifier))],
            dry_run=dry_run)

        # Set output.properties.commit, this will also set the commit as the
        # build output.
        api.src_state.gitiles_commit = internal_snapshot_commit
        api.cros_tags.add_tags_to_current_build(
            **{'published_snapshot_id': internal_snapshot_commit.id})

      with api.step.nest('publish snapshot metadata'):
        # Publish external snapshot metadata.
        api.binhost_lookup_service.publish_snapshot_metadata(
            external_snapshot_commit.id, snapshot_identifier, True,
            api.buildbucket.build.id)
        # Publish internal snapshot metadata.
        api.binhost_lookup_service.publish_snapshot_metadata(
            internal_snapshot_commit.id, snapshot_identifier, False,
            api.buildbucket.build.id)


def _sync_manifest(api, _properties, manifest_ref, prior_internal,
                   prior_external, internal_manifest, external_manifest):
  """Find and push local manifest differences

  Must be called with CWD=external manifest.

  Args:
      api (object):       See RunSteps documentation
      _properties:         Properties of current annealing run
      manifest_ref:       The name of the git branch to create snapshots on
      prior_internal:     Previous commit of internal manifest
      prior_external:     Previous commit of external manifest
      internal_manifest:  Information about internal manifest
      external_manifest:  Information about external manifest

  Return:
    diff_paths(dict): Dictionary containing paths to manifest changes
  """
  with api.step.nest('sync manifests') as presentation:
    presentation.logs['prior versions'] = 'internal {}: {}'.format(
        manifest_ref, prior_internal) + '\nexternal {}: {}'.format(
            manifest_ref, prior_external)

    m_files = api.cros_source.mirrored_manifest_files
    e_paths = []
    for m_file in m_files:
      i_path = internal_manifest.path.join(m_file.src)
      e_path = external_manifest.path.join(m_file.dest)
      if m_file.src != 'external_full.xml':
        api.path.mock_add_paths(i_path)
      if api.path.exists(i_path):
        e_paths.append(e_path)
        api.file.copy('Copy manifest-internal/{}'.format(m_file.src), i_path,
                      e_path)

    repo = api.git.repository_root()
    diff_paths = collections.defaultdict(list)
    for e_path in e_paths:
      if api.git.diff_check(e_path):
        diff_paths[repo].append(api.path.abspath(e_path))
    presentation.logs['diffs'] = json.dumps(diff_paths, sort_keys=True,
                                            indent=2, separators=(',', ':'))
    return diff_paths


def _remove_notice_node(api: RecipeApi, xml_data: str, step_name: str):
  """Remove any <notice> elements from the source XML tree.

    Args:
      api:                  See RunSteps documentation
      manifest_xml_content: String repr of XML tree
      step_name:            Name of step in LUCI/MILO

    Return:
      xml_result(str): Modified XML content
    """
  with api.step.nest(step_name) as presentation:
    root = ElementTree.fromstring(xml_data)
    for element in root.findall('notice'):
      root.remove(element)
    xml_result = ElementTree.tostring(root)
    presentation.logs['xml result'] = xml_result
  return xml_result


def _uprev_packages(api, properties, workspace_path, manifest_diffs, dry_run):
  """Uprev any packages that contain differences

    Args:
      api (object):   See RunSteps documentation
      properties:     Properties of current annealing run
      workspace_path: Path to the workspace checkout
      manifest_diffs: Manifest differences to be upreved
      dry_run:        Dry run git push or not

    Return:
      all_uprevs_passed(bool): True if all uprevs succeeded, False if ANY failed
  """
  is_staging = not properties.publish_uprevs
  uprev_info = []
  with api.step.nest('uprev packages'):
    response = api.cros_source.uprev_packages(workspace_path=workspace_path)
    compressed_response = base64.b64encode(
        zlib.compress(response.SerializeToString()))
    api.easy.set_properties_step(compressed_uprev_response=compressed_response)
    for ebuild in response.modified_ebuilds:
      # TODO(b/192099206): When recipes moves to python3 clean this up with
      # default values
      uprev_info.append(
          api.cros_source.PushUprevRequest([ebuild.path],
                                           'Marking set of ebuilds as stable'))

    with api.step.nest('revbump chrome'):
      responses = api.cros_build_api.PackageService.RevBumpChrome(
          RevBumpChromeRequest(), name='revbump chrome').responses

      for response in responses:
        for ebuild in response.modified_ebuilds:
          uprev_info.append(
              api.cros_source.PushUprevRequest([ebuild.path],
                                               'Revbumping chrome'))

    # Treat the manifest changes as if they were an uprev
    for _, files in manifest_diffs.items():
      for manifest in files:
        # TODO(b/192099206): When recipes moves to python3 clean this up with
        # default values
        uprev_info.append(
            api.cros_source.PushUprevRequest([manifest],
                                             'Syncing with internal manifest'))

  # Push the uprevs to the remote
  return api.cros_source.push_uprev(uprev_info, dry_run, is_staging=is_staging)


def _publish_snapshot(api, repo_url, snapshot_ref, prior_commit, snapshot_file,
                      snapshot_xml, gerrit_commits=None, disable_gerrit=False,
                      footers=None, dry_run=False):
  """Generate snapshot.xml file and commit it to a ref.

  Does not call api.context() so the cwd should be set to the appropriate
  path in the workspace for a git fetch to work.

  Args:
      api (object):   See RunSteps documentation
      repo_url:       URL to git repo to publish snapshot.xml file to
      snapshot_ref:   git ref to publish to (e.g.: 'snapshot')
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
      commit_message += '\n'
      for key, val in footers:
        commit_message += '%s: %s\n' % (key, val)

    if not dry_run:
      api.git_txn.update_ref_write_files(repo_url, commit_message,
                                         [(snapshot_file, snapshot_xml)],
                                         ref=snapshot_ref)
    return _make_gitiles_commit(api, repo_url, 'refs/heads/%s' % snapshot_ref,
                                api.git.head_commit())


def _get_gerrit_changes(api, manifest_diffs):
  """Find all Gerrit changes that landed since the last snapshot.

  Args:
    * api (object): See RunSteps documentation.
    * manifest_diffs (list[ManifestDiff]): Diffs from ToT to last snapshot.

  Returns:
    tuple(
      list[Commit]: The Gerrit-reviewed commits since the last snapshot,
  """
  with api.step.nest('record new gerrit changes') as pres:
    gerrit_changes = []
    gerrit_commits = []
    for diff in manifest_diffs:
      with api.step.nest(diff.path) as step, api.context(
          cwd=api.src_state.workspace_path.join(diff.path)):
        commits = api.git.log(diff.from_rev, diff.to_rev, limit=30)
        for commit in commits:
          reviewed_on_footers = api.git_footers.from_message(
              commit.message, key='Reviewed-on')

          # We have seen bad Reviewed-On footers before (usually from
          # third_party repos pulled from partners with on-premise gerrit
          # instances).  Filter for our gerrit instances explicitly and ignore
          # the rest.
          reviewed_on_footers = [
              footer for footer in reviewed_on_footers
              if 'googlesource.com' in footer
          ]

          if reviewed_on_footers:
            gerrit_change_url = reviewed_on_footers[0]
            gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
            gerrit_change.project = gerrit_change.project or diff.name
            gerrit_change_title = api.naming.get_commit_title(commit)
            step.links[gerrit_change_title] = gerrit_change_url
            gerrit_changes.append(gerrit_change)
            gerrit_commits.append(commit)

    # The GerritChanges parsed from the footers above don't have patchset
    # numbers set. Downstream consumers need these patchset numbers, so
    # find them with gerrit.fetch_patch_sets.
    with api.step.nest('find most recent revisions') as pres:
      # If a repo is checked out to multiple locations in the manifest (e.g.
      # infra/proto), changes to the repo will appear multiple times in
      # gerrit_changes. This will cause issues for fetch_patch_sets, so de-dupe
      # the changes first.
      unique_gerrit_changes = {(gc.host, gc.change): gc for gc in gerrit_changes
                              }.values()

      # Hosts besides chromium-review and chrome-internal-review may not work
      # with fetch_patch_sets because the ChromeOS service accounts don't have
      # access to the APIs for those hosts. Filter out other hosts.
      filtered_gerrit_changes = []
      ignored_gerrit_changes = []
      for gc in unique_gerrit_changes:
        if gc.host in ('chromium-review.googlesource.com',
                       'chrome-internal-review.googlesource.com'):
          filtered_gerrit_changes.append(gc)
        else:
          ignored_gerrit_changes.append(gc)

      if ignored_gerrit_changes:
        pres.logs['ignored gerrit changes'] = [
            json_format.MessageToJson(gc) for gc in ignored_gerrit_changes
        ]

      if filtered_gerrit_changes:
        patch_sets = api.gerrit.fetch_patch_sets(filtered_gerrit_changes)
        # Host and change number uniquely identify a change. Use the patchset
        # numbers returned from fetch_patch_sets to set the patchset on the
        # GerritChanges.
        host_number_to_patchset = {
            (ps.host, ps.change_id): ps.patch_set for ps in patch_sets
        }
        for gc in filtered_gerrit_changes:
          gc.patchset = host_number_to_patchset[(gc.host, gc.change)]

      # Store the found gerrit changes as an output prop, so other builds can use
      # them (e.g. the snapshot orchestrator needs the relevant gerrit changes for
      # test planning).
      pres.properties['found_gerrit_changes'] = [
          json_format.MessageToJson(gc) for gc in filtered_gerrit_changes
      ]

    # TODO(evanhernandez): Storing/returning these commits is a stain.
    # Stop this once the Milo blame list accepts Gerrit changes as input.
    return gerrit_commits


def _make_gitiles_commit(_api, repo_url, ref, commit_id):
  """Create a GitilesCommit for the given |repo_url|, |ref|, and |commit_id|."""
  url = urllib.parse.urlparse(repo_url)
  return GitilesCommit(
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

  # At some point, we need to update the manifest test data to reflect something
  # closer to the actual manifests we process.
  yield api.test(
      'basic',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
  )

  yield api.test(
      'staging-basic',
      api.buildbucket.generic_build(builder='staging-Annealing',
                                    bucket='staging'),
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
  )

  yield api.test(
      'no-snapshot-identifier',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" remote="cros-internal" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" remote="cros-internal" '
              'revision="FROM_REV"/></manifest>')),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.git_footers.step_data(
          'fetch previous snapshot identifier.read git footers', ''),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'snapshot-manifest-has-manifest-change',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers',
          api.gerrit.test_gerrit_change_url()),
      api.gerrit.set_gerrit_fetch_changes_response(
          'record new gerrit changes.find most recent revisions',
          changes=[
              GerritChange(host='chromium-review.googlesource.com',
                           project='chromiumos/chromite', change=1)
          ],
          values_dict={1: {
              'revision_info': {
                  '_number': 5,
              },
          }},
      ),
      api.post_process(post_process.PropertyEquals, 'found_gerrit_changes', [
          '{\n  "host": "chromium-review.googlesource.com",\n  "project": "chromiumos/chromite",\n  "change": "1",\n  "patchset": "5"\n}'
      ]),
  )

  yield api.test(
      'gerrit-change-to-excluded-host',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers',
          'https://pigweed-review.googlesource.com/c/pigweed/+/1'),
      api.post_process(post_process.PropertyEquals, 'found_gerrit_changes', []),
      api.post_process(post_process.LogContains,
                       'record new gerrit changes.find most recent revisions',
                       'ignored gerrit changes',
                       ['pigweed-review.googlesource.com']),
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

  yield api.test(
      'uprev-manifest-changes',
      api.properties(
          AnnealingProperties(manifest_ref='main', publish_uprevs=True,
                              dry_run=False)), api.git.diff_check(True),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     ('manifest\nsrc/overlay\nsrc/private-overlay')))

  # No changes in the manifest at all.
  yield api.test(
      'no-change',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="FROM_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="FROM_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
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
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
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
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
  )

  yield api.test(
      'retry-fetch-first',
      api.properties(
          AnnealingProperties(manifest_ref='snapshot', dry_run=False)),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.step_data(
          ('push uprevs.push to src/private-overlay.git push '
           'src/private-overlay'), retcode=1,
          stdout=api.raw_io.output_text('!	HEAD:refs/heads/staging-infra'
                                        '-main	[rejected] (fetch first)')),
      api.step_data(
          'push uprevs.push to src/overlay.git push src/overlay', retcode=1,
          stdout=api.raw_io.output_text('!	HEAD:refs/heads/staging-infra'
                                        '-main	[rejected] (fetch first)')),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(
          post_process.MustRun,
          ('push uprevs.push to src/overlay.retry uprev to src/overlay.git '
           'push src/overlay')),
      api.post_check(post_process.MustRun,
                     ('push uprevs.push to src/private-overlay.retry uprev to '
                      'src/private-overlay.git push src/private-overlay')),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     ('src/overlay\nsrc/private-overlay')))

  yield api.test(
      'retry-fast-forward',
      api.properties(
          AnnealingProperties(manifest_ref='snapshot', dry_run=False)),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.step_data(
          ('push uprevs.push to src/private-overlay.git push '
           'src/private-overlay'), retcode=1,
          stdout=api.raw_io.output_text('!	HEAD:refs/heads/staging-infra-main	'
                                        '[rejected] (non-fast-forward)')),
      api.step_data(
          'push uprevs.push to src/overlay.git push src/overlay', retcode=1,
          stdout=api.raw_io.output_text('!	HEAD:refs/heads/staging-infra-main	'
                                        '[rejected] (non-fast-forward)')),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(
          post_process.MustRun,
          ('push uprevs.push to src/overlay.retry uprev to src/overlay.git '
           'push src/overlay')),
      api.post_check(post_process.MustRun,
                     ('push uprevs.push to src/private-overlay.retry uprev to '
                      'src/private-overlay.git push src/private-overlay')),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     ('src/overlay\nsrc/private-overlay')))

  yield api.test(
      'retry-no-change',
      api.properties(
          AnnealingProperties(manifest_ref='snapshot', dry_run=False)),
      api.step_data(
          ('push uprevs.push to src/private-overlay.git push '
           'src/private-overlay'), retcode=1, stdout=api.raw_io.output_text(
               ' ! [remote rejected]   HEAD -> main (no new changes)')),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     'src/overlay'),
  )

  yield api.test(
      'retry-fail',
      api.properties(
          AnnealingProperties(manifest_ref='snapshot', dry_run=False,
                              publish_uprevs=True)),
      api.step_data(('push uprevs.push to src/private-overlay.git push '
                     'src/private-overlay'), retcode=1,
                    stdout=api.raw_io.output_text(
                        ('!	HEAD:refs/heads/staging-'
                         'infra-main	[rejected] (fetch first)'))),
      api.step_data(
          ('push uprevs.push to src/private-overlay.retry uprev to '
           'src/private-overlay.git push src/private-overlay'),
          retcode=1,
      ),
      api.step_data(
          ('push uprevs.push to src/private-overlay.retry uprev to '
           'src/private-overlay.git push src/private-overlay (2)'),
          retcode=1,
      ),
      api.step_data(
          ('push uprevs.push to src/private-overlay.retry uprev to '
           'src/private-overlay.git push src/private-overlay (3)'),
          retcode=1,
      ),
      api.post_check(
          post_process.StepWarning,
          'push uprevs.push to src/private-overlay.git push src/private-overlay'
      ),
      api.post_check(
          post_process.MustRun,
          'push uprevs.push to src/private-overlay.git push src/private-overlay'
      ),
      api.post_check(post_process.MustRun,
                     'push uprevs.push to src/overlay.git push src/overlay'),
      api.post_check(post_process.StepException, 'push uprevs'),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Failed Uprevs',
                     'src/private-overlay'),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     'src/overlay'),
      # TODO (b/275363240): audit this test.
      status='FAILURE')

  yield api.test(
      'retry-unknown',
      api.properties(
          AnnealingProperties(manifest_ref='snapshot', dry_run=False)),
      api.step_data(('push uprevs.push to src/private-overlay.git push '
                     'src/private-overlay'), retcode=1),
      api.post_check(
          post_process.StepException,
          'push uprevs.push to src/private-overlay.git push src/private-overlay'
      ),
      api.post_check(
          post_process.MustRun,
          'push uprevs.push to src/private-overlay.git push src/private-overlay'
      ),
      api.post_check(post_process.MustRun,
                     'push uprevs.push to src/overlay.git push src/overlay'),
      api.post_check(post_process.StepException, 'push uprevs'),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Failed Uprevs',
                     'src/private-overlay'),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     'src/overlay'),
      # TODO (b/275363240): audit this test.
      status='FAILURE')

  # CQ: manifest changes, but no gerrit change to go with it.
  yield api.test(
      'cq-build',
      api.buildbucket.try_build(project='chromeos',
                                git_repo=api.src_state.internal_manifest.url,
                                git_ref='refs/heads/snapshot'),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.properties(
          AnnealingProperties(manifest_ref='snapshot'),
          **api.binhost_lookup_service.input_properties),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
      api.post_check(post_process.MustRun, 'publish snapshot metadata'),
  )

  yield api.test(
      'cq-build-no-footer',
      api.buildbucket.try_build(project='chromeos',
                                git_repo=api.src_state.internal_manifest.url,
                                git_ref='refs/heads/snapshot'),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data('recreating older run.read git footers',
                    stdout=api.raw_io.output('')),
      api.post_check(post_process.DoesNotRun, 'record new gerrit changes'),
      api.post_check(post_process.DoesNotRun, 'publish internal snapshot'),
      status='FAILURE',
  )

  # CQ without bb commit: manifest changes, but no gerrit change to go with it.
  yield api.test(
      'cq-build-no-commit', api.cv(run_mode=api.cv.FULL_RUN),
      api.properties(
          AnnealingProperties(manifest_ref='snapshot'),
          **api.binhost_lookup_service.input_properties),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
      api.post_check(post_process.MustRun, 'publish snapshot metadata'))

  yield api.test(
      'only-ignored-gerrit-change',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '<project name="SNAP" revision="TO_REV"><annotation '
              'name="snapshot-mode" value="ignore-diff"/></project>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
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
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
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
      status='FAILURE',
  )

  # TODO(crbug/1169277) this will become multiple tests.
  yield api.test(
      'downrev',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.step_data('check reachability.git merge-base', retcode=1),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
  )

  yield api.test(
      'downrev-staging-allow-cq-depends',
      api.properties(
          AnnealingProperties(manifest_ref='staging-snapshot', dry_run=True,
                              publish_uprevs=False)),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
  )

  yield api.test(
      'crbug-1169277-ignored-downrev',
      api.properties(
          AnnealingProperties(manifest_ref='snapshot',
                              ignore_downrev_paths=['NAME'])),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.step_data('check reachability.git merge-base', retcode=1),
      api.git_footers.step_data(
          'record new gerrit changes.NAME.read git footers', ''),
      api.post_check(post_process.MustRun, 'record new gerrit changes'),
      api.post_check(post_process.MustRun, 'publish internal snapshot'),
  )

  yield api.test(
      'cq-deps-failure',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.step_data('ensure manifest cq-depend fulfilled.git log', retcode=3),
      status='INFRA_FAILURE',
  )

  # Publish metadata fails when required properties are not passed.
  yield api.test(
      'publish-metadata-no-properties-failure',
      api.buildbucket.try_build(project='chromeos',
                                git_repo=api.src_state.internal_manifest.url,
                                git_ref='refs/heads/snapshot'),
      api.cv(run_mode=api.cv.FULL_RUN),
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'generate internal manifest', stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>')),
      api.step_data(
          'diff remote and local manifest.git show',
          stdout=api.raw_io.output_text(
              '<manifest><project name="NAME" revision="FROM_REV" /></manifest>'
          )),
      api.post_check(post_process.StepException, 'publish snapshot metadata'),
      api.post_check(post_process.DropExpectation))

  yield api.test(
      'remove-notice-tag-from-manifest-xml',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<notice>Hi!</notice>'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>'),
      ),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<notice>Hi!</notice>'
              '<project name="NAME" remote="cros-internal" revision="TO_REV"/>'
              '</manifest>'),
      ),
      api.post_check(post_process.MustRun,
                     'remove <notice> from external manifest'),
      api.post_check(post_process.MustRun,
                     'remove <notice> from internal manifest'),
      api.post_check(
          post_process.LogEquals,
          'remove <notice> from external manifest',
          'xml result',
          '<manifest visibility="external">'
          '<project name="NAME" revision="TO_REV" />'
          '</manifest>',
      ),
      api.post_check(
          post_process.LogEquals,
          'remove <notice> from internal manifest',
          'xml result',
          '<manifest visibility="internal">'
          '<project name="NAME" remote="cros-internal" revision="TO_REV" />'
          '</manifest>',
      ),
      # We make no assertions in this test that a diff was generated so a Gerrit
      # CL is unnecessary. We do want to ensure that subsequent steps run.
      api.post_check(post_process.MustRun, 'diff remote and local manifest'),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'remove-missing-notice-tag-from-manifest-xml-succeeds',
      api.properties(AnnealingProperties(manifest_ref='snapshot')),
      api.step_data(
          'generate external manifest',
          stdout=api.raw_io.output_text(
              '<manifest visibility="external">'
              '<project name="NAME" revision="TO_REV"/>'
              '</manifest>'),
      ),
      api.step_data(
          'generate internal manifest',
          stdout=api.raw_io.output_text(
              '<manifest visibility="internal">'
              '<project name="NAME" remote="cros-internal" revision="TO_REV"/>'
              '</manifest>'),
      ),
      api.post_check(post_process.StepSuccess,
                     'remove <notice> from external manifest'),
      api.post_check(
          post_process.LogEquals,
          'remove <notice> from external manifest',
          'xml result',
          '<manifest visibility="external">'
          '<project name="NAME" revision="TO_REV" />'
          '</manifest>',
      ),
      api.post_check(post_process.StepSuccess,
                     'remove <notice> from internal manifest'),
      api.post_check(
          post_process.LogEquals,
          'remove <notice> from internal manifest',
          'xml result',
          '<manifest visibility="internal">'
          '<project name="NAME" remote="cros-internal" revision="TO_REV" />'
          '</manifest>',
      ),
      # We make no assertions in this test that a diff was generated so a Gerrit
      # CL is unnecessary. We do want to ensure that subsequent steps run.
      api.post_check(post_process.MustRun, 'diff remote and local manifest'),
      api.post_check(post_process.DropExpectation),
  )
