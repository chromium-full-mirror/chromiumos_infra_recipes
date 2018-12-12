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
    'overlayfs',
    'repo',
    'repo_cache',
]

MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'


def RunSteps(api):
  # Cache the chroot.
  api.cros.set_config(CHROOT_PATH=api.path['cache'].join('cros_chroot'))

  repo_cache_path = api.repo_cache.ensure_fresh_cache(
      'chromiumos', MANIFEST_URL, init_opts=dict(groups=['minilayout']))

  master_path = api.cros.master_src_path
  workspace_path = api.cros.workspace_src_path

  with api.overlayfs.context('master', repo_cache_path, master_path), \
        api.overlayfs.context('workspace', repo_cache_path, workspace_path):
    api.cros.regen_portage_cache('chromiumos')


def GenTests(api):
  yield api.test('basic')
