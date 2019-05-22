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

import urlparse

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.annealing import AnnealingProperties

from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_source',
    'depends',
    'gerrit',
    'git',
    'git_footers',
    'git_txn',
    'repo',
]


PROPERTIES = AnnealingProperties


def RunSteps(api, properties):
  manifest_ref = properties.manifest_ref
  if not manifest_ref:
    raise ValueError('must set manifest ref')

  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context(), api.context(
      cwd=api.cros_source.workspace_path.join('manifest-internal')):

    snapshot_xml = api.repo.manifest_snapshot()
    manifest_diffs = api.repo.diff_remote_and_local_manifests(
        api.cros_source.INTERNAL_MANIFEST_URL, manifest_ref, snapshot_xml)

    # TODO(athilenius): It would be nice to set the 'Info' column here.
    if manifest_diffs is not None:
      # If there are zero diffs (empty array) then there is nothing
      # interesting to be done.
      if len(manifest_diffs) == 0:
        return

      # Otherwise we need to ensure all of those diffs have fulfilled deps.
      api.depends.ensure_manifest_cq_depends_fulfilled(manifest_diffs)

      # Then, record the diffs. We are specifically interested in what
      # gerrit changes have landed.
      record_gerrit_changes(api, manifest_diffs)

    snapshot_repo_url = api.cros_source.INTERNAL_MANIFEST_URL
    api.git.fetch_ref(snapshot_repo_url, manifest_ref)
    api.git.checkout('FETCH_HEAD')
    api.git_txn.update_ref_write_file(
        snapshot_repo_url, manifest_ref, make_message(api, manifest_ref),
        api.cros_source.workspace_path.join('manifest-internal/snapshot.xml'),
        snapshot_xml)

    # Use the newly created snapshot commit as the build output.
    snapshot_commit = make_gitiles_commit(api, snapshot_repo_url,
                                          api.git.head_commit())
    api.buildbucket.set_output_gitiles_commit(snapshot_commit)


def record_gerrit_changes(api, manifest_diffs):
  """Find all Gerrit changes that landed since the last snapshot.

  Args:
    * api (object): See RunSteps documentation.
    * manifest_diffs (list[ManifestDiff]): Diffs from ToT to last snapshot.
  """
  with api.step.nest('record new gerrit changes') as step:
    for diff in manifest_diffs:
      with api.context(cwd=api.cros_source.workspace_path.join(diff.path)):
        commits = api.git.log(diff.from_rev, diff.to_rev)
        for commit in commits:
          reviewed_on_footers = api.git_footers.get(commit.rev, 'Reviewed-on')
          if reviewed_on_footers:
            gerrit_change_url = reviewed_on_footers[0]
            gerrit_change = api.gerrit.parse_gerrit_change(gerrit_change_url)
            step.presentation.logs[gerrit_change_url] = [str(gerrit_change)]
          # TODO(evanhernandez): Also upload to Isolate.


def make_gitiles_commit(api, repo_url, commit_id):
  """Create a GitilesCommit for the given |repo_url| and |commit_id|."""
  url = urlparse.urlparse(repo_url)
  return common_pb2.GitilesCommit(
      host=url.hostname,
      project=url.path[1:], # strip leading /
      ref='refs/heads/master',
      id=commit_id,
  )


def make_message(api, manifest_ref):
  """Creates and returns the commit message with a Cr-Commit-Position.

  Creates and returns the commit message with a Cr-Commit-Position
  suitable for use by FindIt, as in:

  Cr-Commit-Position: refs/heads/snapshot@{#%d}

  Args:
    * api (object): See RunSteps documentation.
    * manifest_ref (str): The git reference to use in the commit message.

  Returns:
    A string containing the commit message.
  """
  position = api.git.position_num()
  message = 'Annealing manifest snapshot\n\n'
  message += 'Cr-Commit-Position: refs/heads/%s@{#%d}' % (manifest_ref,
                                                          position + 1)
  return message


def GenTests(api):
  yield (api.test('basic') +  #
         api.properties(AnnealingProperties(manifest_ref='snapshot')))

  yield (
      api.test('has manifest change') +  #
      api.properties(AnnealingProperties(manifest_ref='snapshot')) +  #
      api.step_data(
          'repo manifest', stdout=api.raw_io.output(
              '<manifest><project path="PATH" revision="TO_REV" /></manifest>'))
      +  #
      api.step_data(
          'diff remote and local manifest.git show', stdout=api.raw_io.output(
              '<manifest><project path="PATH" revision="FROM_REV" /></manifest>'
          )) + #
      api.git_footers.step_data(
          'record new gerrit changes.git_footers.py',
          api.gerrit.test_gerrit_change_url()))

  yield (api.test('missing required properties') +  #
         api.properties(AnnealingProperties()) + #
         api.expect_exception('ValueError'))
