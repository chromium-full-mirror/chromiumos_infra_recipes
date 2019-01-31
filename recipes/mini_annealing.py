# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Chrome OS mini-annealing builders.

The mini annealing builder is a subset of the full annealing builder and simply
snapshots ToT.

1. Checkout ToT
4. Make a manifest snapshot (aka "revlocked manifest"), and push it
   to `chromiumos/manifest` on the `annealing-test` branch.
"""

DEPS = [
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
    'repo_cache',
]

MANIFEST_REF = 'snapshot'


def RunSteps(api):
  api.dev.configure(dryrun=False)

  # Cache the chroot.
  api.cros_sdk.configure(
      chroot_parent_path=api.path['cache'].join('cros_chroot'))

  # Prepare repo source cache.
  repo_cache_path = api.path['cache'].join('chromiumos')
  api.repo_cache.ensure_fresh_cache(repo_cache_path,
                                    api.cros_source.INTERNAL_MANIFEST_URL)

  with api.cros_source.checkout_overlays_context(repo_cache_path), api.context(
      cwd=api.cros_source.workspace_path.join('manifest-internal')):

      snapshot_xml = api.repo.manifest_snapshot()
      manifest_diffs = api.repo.diff_remote_and_local_manifests(
          api.cros_source.INTERNAL_MANIFEST_URL, MANIFEST_REF, snapshot_xml)

      # Nothing interesting to be done if the manifest didn't change in any
      # meaningful way.
      # TODO(athilenius): It would be nice to set the 'Info' column here.
      if not manifest_diffs:
        return

      api.depends.ensure_manifest_cq_depends_fulfilled(manifest_diffs)
      api.git_txn.update_ref_write_file(
          api.cros_source.INTERNAL_MANIFEST_URL, MANIFEST_REF,
          'Annealing manifest snapshot',
          api.cros_source.workspace_path.join('manifest-internal/snapshot.xml'),
          snapshot_xml)


def GenTests(api):
  yield api.test('basic')

  yield api.test('has manifest change') + api.step_data(
      'repo manifest', stdout=api.raw_io.output(
          '<manifest><project path="PATH" revision="TO_REV" /></manifest>')
  ) + api.step_data(
      'diff remote and local manifest.git show', stdout=api.raw_io.output(
          '<manifest><project path="PATH" revision="FROM_REV" /></manifest>'))
