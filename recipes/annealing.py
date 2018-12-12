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
    'cros_sdk',
    'overlayfs',
    'repo',
    'repo_cache',
]

MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'


def RunSteps(api):
  # Cache the chroot.
  api.cros_sdk.configure(chroot_parent_path=api.path['cache'].join('cros_chroot'))

  # Refresh and mount repo cache.
  api.repo_cache.ensure_fresh_cache(init_opts=dict(groups=['minilayout']))
  with api.overlayfs.context('master', api.repo_cache.path, api.cros.master_path), \
        api.overlayfs.context('workspace', api.repo_cache.path, api.cros.workspace_path):
    api.cros.regen_portage_cache(repo_name='chromiumos')


def GenTests(api):
  yield api.test('basic')
