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
      # We'll have a list of updated overlays, but some might be in the same git
      # project, so we have to dedupe as we go.
      if overlays:
        overlay_dirs = [overlay.path for overlay in overlays]
        with api.step.nest('commit and push metadata'):
          projects = api.repo.project_infos(projects=overlay_dirs)
          for project in projects:
            with api.context(
                cwd=api.cros_source.workspace_path.join(project.path)):
              api.git_txn.update_ref(project.remote, _add_and_commit,
                                     ref=project.branch, automerge=True)


def GenTests(api):
  yield api.test('basic')
