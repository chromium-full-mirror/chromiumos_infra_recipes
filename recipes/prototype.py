# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for prototyping Chrome OS builders."""

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'changes',
    'cros',
    'cros_sdk',
    'dev',
    'overlayfs',
    'repo',
    'repo_cache',
]

MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'


def RunSteps(api):
  # Set dryrun by default, for now
  api.dev.configure(dryrun=True)
  # Cache the chroot.
  # TODO(lannm): Need to cleanup or use another overlay (?)
  api.cros_sdk.configure(chroot_parent_path=api.path['cache'].join('cros_chroot'))

  # Refresh and mount repo cache.
  api.repo_cache.ensure_fresh_cache(init_opts=dict(groups=['minilayout']))
  with api.overlayfs.context('master', api.repo_cache.path, api.cros.master_path), \
        api.overlayfs.context('workspace', api.repo_cache.path, api.cros.workspace_path):
    changes = api.changes.get_changes()
    api.cros.cherry_pick_changes(changes)


def GenTests(api):
  yield api.test('basic')
