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
    'cros_bisect',
    'cros_sdk',
    'cros_source',
    'dev',
    'gerrit',
    'overlayfs',
    'repo',
    'sync_chrome',
]

from recipe_engine.config import Dict
from recipe_engine.recipe_api import Property

PROPERTIES = {
    'build_target': Property(kind=Dict()),
    # Whether or not to build an image.
    'build_image': Property(kind=bool, default=True),
}


def _run_cros_sdk_script(api, script, target, *args):
  # TODO: Replace with Build API equivalents.
  cmd = ['/mnt/host/source/src/scripts/%s' % script, '--board', target]
  if args:
    cmd.extend(args)
  api.cros_sdk.run(script, cmd)


def RunSteps(api, build_target, build_image):
  build_target_name = build_target['name']

  api.cros_bisect.set_bisect_builder(build_target_name)

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      # Sync workspace to gitiles_commit manifest snapshot.
      api.cros_source.sync_gitiles_snapshot(api.buildbucket.gitiles_commit)

      # sync_chrome must run inside a chromiumos source root.
      chrome_root = api.path['cache'].join('chrome')
      api.sync_chrome.sync_chrome(chrome_root)

      # Use a named cache for the chroot.
      api.cros_sdk.configure(
          chroot_parent_path=api.path['cache'].join('cros_chroot'),
          chrome_root=chrome_root)

      _run_cros_sdk_script(api, 'setup_board', build_target_name)

      # Packages subset will be present when FindIt asks for bisection build.
      packages = api.cros_bisect.get_packages()
      _run_cros_sdk_script(api, 'build_packages', build_target_name, *packages)

      if build_image:
        _run_cros_sdk_script(api, 'build_image', build_target_name)


def GenTests(api):
  yield (api.test('basic') +  #
         api.properties(build_target={'name': 'generic'}))

  yield (api.test('with-findit-bisect') +  #
         api.properties(
             build_target={'name': 'generic'},
             findit_bisect={'targets': ['foo', 'bar', 'baz']},
             build_image=False,
         ))
