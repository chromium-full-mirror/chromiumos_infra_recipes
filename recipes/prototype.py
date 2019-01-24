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
    'cros_sdk',
    'cros_source',
    'dev',
    'gerrit',
    'overlayfs',
    'repo',
    'repo_cache',
]

MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'


def RunSteps(api):
  with api.overlayfs.cleanup_context():
    # Set dryrun to prevent accidental e.g. git pushes.
    api.dev.configure(dryrun=True)

    # Use a named cache for the chroot.
    chroot_parent_path = api.path['cache'].join('cros_chroot')
    api.cros_sdk.configure(chroot_parent_path=chroot_parent_path)

    # Refresh repo source cache.
    api.repo_cache.ensure_fresh_cache(init_opts=dict(groups=['minilayout']))

    # Mount repo source overlays.
    api.overlayfs.mount('master', api.repo_cache.path,
                        api.cros_source.master_path)
    api.overlayfs.mount('workspace', api.repo_cache.path,
                        api.cros_source.workspace_path)

    # Fetch and apply Gerrit changes.
    gerrit_changes = api.buildbucket.build.input.gerrit_changes
    patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
    api.cros_source.apply_gerrit_patch_sets(patch_sets)


def GenTests(api):
  yield api.test('basic')
