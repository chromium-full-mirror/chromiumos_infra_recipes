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
  'recipe_engine/step',
  'cros',
  'cros_build',
  'cros_sdk',
  'depends',
  'dev',
  'git',
  'git_txn',
  'overlayfs',
  'repo',
  'repo_cache',
]

MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'
MANIFEST_REF = 'annealing-test'


def RunSteps(api):
  with api.overlayfs.cleanup_context():
    # Set annealing into dryrun mode by default. Comment / uncomment as needed
    # for testing.
    api.dev.configure(dryrun=False)

    # Cache the chroot.
    api.cros_sdk.configure(
        chroot_parent_path=api.path['cache'].join('cros_chroot'))

    # Refresh and mount repo cache.
    api.repo_cache.ensure_fresh_cache()
    api.overlayfs.mount('master', api.repo_cache.path, api.cros.master_path)
    api.overlayfs.mount('workspace', api.repo_cache.path,
                        api.cros.workspace_path)

    with api.context(cwd=api.cros.workspace_path.join('manifest')):
      snapshot_xml = api.repo.manifest_snapshot()
      api.depends.ensure_manifest_cq_depends_fulfilled(MANIFEST_REF,
                                                       snapshot_xml)

      # Create, commit and push the actual snapshot.
      api.git_txn.update_ref_write_file(MANIFEST_URL, MANIFEST_REF,
                                        'Mini-annealing manifest snapshot',
                                        api.cros.workspace_path.join(
                                            'manifest/snapshot.xml'),
                                        snapshot_xml)


def GenTests(api):
  yield api.test('basic')
