# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for prototyping Chrome OS builders."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros',
    'cros_sdk',
    'dev',
    'gerrit',
    'overlayfs',
    'repo',
    'repo_cache',
]

MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'

# Prepare source tree
# Prepare build environment for build target


def RunSteps(api):
  with api.overlayfs.cleanup_context():
    # Set dryrun by default, for now
    api.dev.configure(dryrun=True)

    # Cache the chroot.
    api.cros_sdk.configure(
        chroot_parent_path=api.path['cache'].join('cros_chroot'))

    # Refresh and mount repo cache.
    api.repo_cache.ensure_fresh_cache(init_opts=dict(groups=['minilayout']))
    api.overlayfs.mount('master', api.repo_cache.path, api.cros.master_path)
    api.overlayfs.mount('workspace', api.repo_cache.path,
                        api.cros.workspace_path)

    # Apply Gerrit changes.
    gerrit_changes = api.buildbucket.build.input.gerrit_changes
    patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
    api.cros.cherry_pick_changes(patch_sets)


def GenTests(api):
  yield api.test('basic')
