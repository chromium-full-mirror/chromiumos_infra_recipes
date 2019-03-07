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

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_sdk',
    'cros_source',
    'depends',
    'dev',
    'git',
    'git_txn',
    'overlayfs',
    'repo',
]

MANIFEST_REF = 'snapshot'


def RunSteps(api):
  # Cache the chroot.
  api.cros_sdk.configure(
      chroot_parent_path=api.path['cache'].join('cros_chroot'))

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context(), api.context(
      cwd=api.cros_source.workspace_path.join('manifest-internal')):

    snapshot_xml = api.repo.manifest_snapshot()
    manifest_diffs = api.repo.diff_remote_and_local_manifests(
        api.cros_source.INTERNAL_MANIFEST_URL, MANIFEST_REF, snapshot_xml)

    # TODO(athilenius): It would be nice to set the 'Info' column here.
    if manifest_diffs is not None:
      # If there are zero diffs (empty array) then there is nothing
      # interesting to be done.
      if len(manifest_diffs) == 0:
        return

      # Otherwise we need to ensure all of those diffs have fulfilled deps.
      api.depends.ensure_manifest_cq_depends_fulfilled(manifest_diffs)

    snapshot_repo_url = api.cros_source.INTERNAL_MANIFEST_URL
    api.git_txn.update_ref_write_file(
        snapshot_repo_url, MANIFEST_REF, make_message(api),
        api.cros_source.workspace_path.join('manifest-internal/snapshot.xml'),
        snapshot_xml)

    # Use the newly created snapshot commit as the build output.
    snapshot_commit = make_gitiles_commit(api, snapshot_repo_url,
                                          api.git.head_commit())
    api.buildbucket.set_output_gitiles_commit(snapshot_commit)


def make_gitiles_commit(api, repo_url, commit_id):
  """Create a GitilesCommit for the given |repo_url| and |commit_id|."""
  url = urlparse.urlparse(repo_url)
  c = common_pb2.GitilesCommit()
  c.host = url.hostname
  c.project = url.path[1:]  # strip leading /
  c.id = commit_id
  return c


def make_message(api):
  """Creates and returns the commit message with a Cr-Commit-Position.

  Creates and returns the commit message with a Cr-Commit-Position
  suitable for use by FindIt, as in:

  Cr-Commit-Position: refs/heads/snapshot@{#%d}

  Note that if a prior commit position is not found this will return a
  commit position that resets back to 1. After this is deployed and
  Cr-Commit-Position is seeded it may be better to remove this fallback
  and have it fail if no prior commit position is found.
  """
  position = api.git.position_num()
  if position is None:
    position = 0
  message = 'Annealing manifest snapshot\n\n'
  message += ('Cr-Commit-Position: refs/heads/%s@{#%d}' %
              (MANIFEST_REF, position + 1))
  return message


def GenTests(api):
  yield api.test('basic')

  yield api.test('has manifest change') + api.step_data(
      'repo manifest', stdout=api.raw_io.output(
          '<manifest><project path="PATH" revision="TO_REV" /></manifest>')
  ) + api.step_data(
      'diff remote and local manifest.git show', stdout=api.raw_io.output(
          '<manifest><project path="PATH" revision="FROM_REV" /></manifest>'))
