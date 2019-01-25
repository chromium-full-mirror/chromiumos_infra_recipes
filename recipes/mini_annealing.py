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

MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'
MANIFEST_REF = 'snapshot'


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
    api.overlayfs.mount('workspace', api.repo_cache.path,
                        api.cros_source.workspace_path)

    with api.context(cwd=api.cros_source.workspace_path.join('manifest')):
      snapshot_xml = api.repo.manifest_snapshot()
      api.depends.ensure_manifest_cq_depends_fulfilled(
          MANIFEST_URL, MANIFEST_REF, snapshot_xml)

      # Create, commit and push the actual snapshot.
      api.git_txn.update_ref_write_file(
          MANIFEST_URL, MANIFEST_REF, 'Annealing manifest snapshot',
          api.cros_source.workspace_path.join('manifest/snapshot.xml'),
          snapshot_xml)


def GenTests(api):
  yield api.test('basic')
