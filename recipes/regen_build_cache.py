# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Chrome OS Build Metadata Cache Regnerator."""

from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromite.api.binhost import RegenBuildCacheRequest

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'git',
    'git_txn',
    'repo',
    'util',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):

  def _add_and_commit():
    api.git.add(['.'])
    api.git.commit('Update Metadata Cache')

  with api.workspace_util.setup_workspace(
      default_main=True), api.cros_sdk.cleanup_context():

    api.cros_source.ensure_synced_cache()
    api.cros_source.checkout_tip_of_tree()
    api.cros_sdk.create_chroot(version=None, use_image=False, timeout_sec=None)
    api.cros_sdk.update_chroot(None, None, timeout_sec=None)

    with api.step.nest('update metadata'), api.context(
        cwd=api.cros_source.workspace_path):
      overlays = api.cros_build_api.BinhostService.RegenBuildCache(
          RegenBuildCacheRequest(overlay_type=OVERLAYTYPE_BOTH,
                                 chroot=api.cros_sdk.chroot)).modified_overlays
      if overlays:
        overlay_dirs = [overlay.path for overlay in overlays]
        with api.step.nest('commit and push metadata'):
          for overlay_dir in overlay_dirs:
            with api.context(cwd=api.path.abs_to_path(overlay_dir)):
              project = api.repo.project_infos(projects=[overlay_dir])[0]
              api.git_txn.update_ref(project.remote, _add_and_commit,
                                     ref=project.branch, automerge=True)


def GenTests(api):
  yield api.test('basic')
