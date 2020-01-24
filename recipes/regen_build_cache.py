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
from PB.chromiumos.builder_config import BuilderConfig

from google.protobuf import json_format as json_pb
from recipe_engine import util

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_build_api',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'easy',
    'git',
    'repo',
]


def RunSteps(api):
  with api.cros_source.checkout_overlays_context(), \
      api.cros_sdk.cleanup_context(
          checkout_path=api.cros_source.workspace_path), \
      api.context(
          cwd=api.cros_source.workspace_path.join('manifest-internal')):

    with api.step.nest('read builder config') as step:
      try:
        build_config = api.cros_infra_config.get_builder_config(
            api.buildbucket.build.builder.builder)
      except LookupError:
        step.presentation.step_text = 'config not found, assuming deleted'
        return
      step.presentation.logs['builder config'] = [str(build_config)]
      api.easy.set_property_step('builder_config',
                                 json_pb.MessageToDict(build_config))

    api.cros_source.ensure_synced_cache()
    with api.step.nest('init sdk') as step:
      api.cros_sdk.build_chmod_chroot()
      no_replace_flag = True
      if build_config.general.sdk_cache_version:
        step.presentation.logs['sdk cache version'] = [
            'Version in config: %s' % build_config.general.sdk_cache_version,
            'Version on disk: %s' % api.cros_sdk.sdk_cache_version,
        ]
        no_replace_flag = (str(build_config.general.sdk_cache_version) ==
                          str(api.cros_sdk.sdk_cache_version))
      response = api.cros_build_api.SdkService.Create(
          CreateSdkRequest(
              flags=CreateSdkRequest.Flags(no_replace=no_replace_flag,
                                           no_use_image=True),
              chroot=api.cros_sdk.chroot))
      step.presentation.logs['sdk version'] = [str(response.version.version)]
      if build_config.general.sdk_cache_version:
        api.cros_sdk.sdk_cache_version = build_config.general.sdk_cache_version
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
                   'HEAD:refs/for/' + project.branch + '%notify=NONE,submit')


def GenTests(api):
  yield (api.test('basic') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='cq',
                                  builder='amd64-generic-cq'))

  yield (
      api.test('initsdk-existing-sdk-cache') +
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                               builder='staging-amd64-generic-cq') +
      api.step_data('init sdk.read sdk cache version json',
                    api.raw_io.output_text('{"version": "2"}')))

  yield (
      api.test('initsdk-existing-outdated-sdk-cache') +
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                              builder='staging-amd64-generic-cq') +
      api.step_data('init sdk.read sdk cache version json',
                    api.raw_io.output_text('{"version": "1"}')))

  yield (api.test('builder-no-longer-exists'))
