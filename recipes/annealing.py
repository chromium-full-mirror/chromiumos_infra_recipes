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

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros',
    'cros_build',
    'cros_sdk',
    'dev',
    'git_txn',
    'overlayfs',
    'repo',
    'repo_cache',
]

MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'


def RunSteps(api):
  with api.overlayfs.cleanup_context():
    # Set annealing into dryrun mode by default. Comment / uncomment as needed
    # for testing.
    api.dev.configure(dryrun=True)

    # Cache the chroot.
    api.cros_sdk.configure(
        chroot_parent_path=api.path['cache'].join('cros_chroot'))

    # Refresh and mount repo cache.
    api.repo_cache.ensure_fresh_cache()
    api.overlayfs.mount('master', api.repo_cache.path, api.cros.master_path)
    api.overlayfs.mount('workspace', api.repo_cache.path,
                        api.cros.workspace_path)

    # Portage uprev packages.
    api.cros_build.regen_portage_cache(repo_name='chromiumos')
    api.cros_build.uprev_portage_packages()
    api.cros_build.push_portage_package_uprevs()

    # Create a manifest snapshot and commit it.
    with api.step.nest('update annealing manifest'):
      snapshot_xml = api.repo.manifest_snapshot()
      with api.context(cwd=api.cros.workspace_path.join('manifest')):
        api.git_txn.update_ref_write_file(
            'https://chromium-review.googlesource.com/chromiumos/infra/recipes',
            'manifest-prototype', 'Annealing manifest snapshot',
            api.cros.workspace_path.join('manifest/snapshot.xml'), snapshot_xml)


def GenTests(api):
  yield api.test('basic')
