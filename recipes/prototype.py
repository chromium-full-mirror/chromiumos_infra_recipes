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
]


def RunSteps(api):
  # Set dryrun to prevent accidental e.g. git pushes.
  api.dev.configure(dryrun=True)

  # Use a named cache for the chroot.
  api.cros_sdk.configure(
      chroot_parent_path=api.path['cache'].join('cros_chroot'))

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache(init_opts=dict(groups=['minilayout']))
  with api.cros_source.checkout_overlays_context():
    # Fetch and apply Gerrit changes.
    gerrit_changes = api.buildbucket.build.input.gerrit_changes
    patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
    api.cros_source.apply_gerrit_patch_sets(patch_sets)


def GenTests(api):
  yield api.test('basic')
