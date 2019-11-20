# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Chrome OS Build Metadata Cache Regnerator."""

import collections

from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromite.api.binhost import RegenBuildCacheRequest
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest

from recipe_engine import util

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'git',
    'repo',
]


def RunSteps(api):
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context(), \
      api.cros_sdk.cleanup_context(
          checkout_path=api.cros_source.workspace_path), \
      api.context(
          cwd=api.cros_source.workspace_path.join('manifest-internal')):

    with api.step.nest('init sdk') as step:
      api.cros_sdk.build_chmod_chroot()
      response = api.cros_build_api.SdkService.Create(
          CreateSdkRequest(
              flags=CreateSdkRequest.Flags(no_replace=True, no_use_image=True),
              chroot=api.cros_sdk.chroot))
      step.presentation.logs['sdk version'] = [str(response.version.version)]
      api.cros_sdk.link_chroot(api.cros_source.workspace_path)

    with api.step.nest('update sdk') as step:
      api.cros_build_api.SdkService.Update(
          UpdateSdkRequest(chroot=api.cros_sdk.chroot))

    with api.step.nest('update metadata'), api.context(
        cwd=api.cros_source.workspace_path):
      overlays = api.cros_build_api.BinhostService.RegenBuildCache(
          RegenBuildCacheRequest(overlay_type=OVERLAYTYPE_BOTH,
                                 chroot=api.cros_sdk.chroot)).modified_overlays
      if overlays:
        overlay_dirs = [overlay.path for overlay in overlays]
        with api.step.nest('commit metadata'):
          for overlay_dir in overlay_dirs:
            with api.context(cwd=api.path.abs_to_path(overlay_dir)):
              api.git.add(['.'])
              api.git.commit('Update Metadata Cache')
        with api.step.nest('push metadata'):
          push = util.exponential_retry(retries=3)(api.git.push)
          for overlay_dir in overlay_dirs:
            with api.context(cwd=api.path.abs_to_path(overlay_dir)):
              project = api.repo.project_infos(projects=[overlay_dir])[0]
              push(project.remote,
                   'HEAD:refs/for/' + project.branch + '%submit')


def GenTests(api):
  yield (api.test('basic'))
