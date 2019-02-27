# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_sdk',
    'cros_source',
    'dev',
    'gerrit',
    'overlayfs',
    'repo',
    'repo_cache',
]

from recipe_engine.config import Dict
from recipe_engine.recipe_api import Property

PROPERTIES = {'build_target': Property(kind=Dict())}


def RunSteps(api, build_target):
  build_target_name = build_target['name']

  # Use a named cache for the chroot.
  api.cros_sdk.configure(
      chroot_parent_path=api.path['cache'].join('cros_chroot'))

  # Prepare repo source cache.
  repo_cache_path = api.path['cache'].join('chromiumos')
  api.repo_cache.ensure_fresh_cache(repo_cache_path,
                                    api.cros_source.INTERNAL_MANIFEST_URL)

  with api.cros_source.checkout_overlays_context(repo_cache_path):
    with api.context(cwd=api.cros_source.workspace_path):
      # Sync workspace to gitiles_commit manifest snapshot.
      api.cros_source.sync_gitiles_snapshot(api.buildbucket.gitiles_commit)

      # Build target image.
      for build_script in ('setup_board', 'build_packages', 'build_image'):
        # TODO: Replace with Build API equivalents.
        api.cros_sdk.run(build_script, [
            '/mnt/host/source/src/scripts/%s' % build_script, '--board',
            build_target_name
        ])


def GenTests(api):
  yield (api.test('basic') +  #
         api.properties(build_target={'name': 'generic'}))
