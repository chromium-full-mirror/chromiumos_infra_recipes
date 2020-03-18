# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that tests chromite.

Though this recipe appears to be almost a subset of build_target, it lives
on its own because it is agnostic of ChromeOS build targets.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'chroot_util',
    'cros_build_api',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'easy',
    'gerrit',
]

from google.protobuf import json_format as json_pb

from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import DeleteRequest as DeleteSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.chromite.api.test import ChromiteUnitTestRequest
from PB.chromiumos.builder_config import BuilderConfig


def RunSteps(api):
  with api.step.nest('read builder config') as pres:
    try:
      config = api.cros_infra_config.get_builder_config(
          api.buildbucket.build.builder.builder)
    except LookupError:
      pres.step_text = 'config not found, assuming deleted'
      return
    pres.logs['builder config'] = [str(config)]
    pres.properties['builder_config'] = json_pb.MessageToDict(config)

  with api.cros_source.checkout_overlays_context(), \
      api.cros_sdk.cleanup_context(
          checkout_path=api.cros_source.workspace_path):
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache()
      api.cros_source.sync_snapshot(api.buildbucket.gitiles_commit)

      gerrit_changes = api.buildbucket.build.input.gerrit_changes
      if gerrit_changes and config.build.apply_gerrit_changes:
        with api.step.nest('cherry-pick gerrit changes'):
          patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
          api.cros_source.apply_gerrit_patch_sets(patch_sets)

      api.chroot_util.init_sdk(version=config.general.sdk_cache_version,
                               use_image=False, timeout_sec=None)

      with api.step.nest('update sdk'):
        try:
          api.cros_build_api.SdkService.Update(
              UpdateSdkRequest(chroot=api.cros_sdk.chroot))
        except api.step.StepFailure:
          # Invalidate the cache if the UpdateSDK call fails.
          api.step.nest(
              'UpdateSDK failure, deleting chroot',
              api.cros_build_api.SdkService.Delete(
                  DeleteSdkRequest(chroot=api.cros_sdk.chroot)))
          raise

      api.cros_build_api.TestService.ChromiteUnitTest(
          ChromiteUnitTestRequest(chroot=api.cros_sdk.chroot),
          name='run chromite unit tests')


def GenTests(api):
  yield (api.test('no-gerrit-changes') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='amd64-generic-postsubmit'))

  yield (api.test('one-gerrit-change') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='chromite-cq'))

  yield (
      api.test('initsdk-destroy-chroot-tests') +  #
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='chromite-cq') +  #
      api.step_data(
          'init sdk.call chromite.api.SdkService/Create.call build API script',
          retcode=1))

  yield (api.test('updatesdk-destroy-chroot-tests') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='chromite-cq') +  #
         api.step_data(
             'update sdk.call chromite.api.SdkService/Update.'
             'call build API script', retcode=1))

  yield (api.test('initsdk-existing-sdk-cache') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='staging-amd64-generic-cq') +  #
         api.step_data('init sdk.read sdk cache version json',
                       api.raw_io.output_text('{"version": "2"}')))

  yield (api.test('initsdk-existing-outdated-sdk-cache') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='staging-amd64-generic-cq') +  #
         api.step_data('init sdk.read sdk cache version json',
                       api.raw_io.output_text('{"version": "1"}')))

  yield (
      api.test('builder-no-longer-exists') +  #
      api.buildbucket.ci_build(project='chromeos', bucket='cq', builder='none'))
