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
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'gerrit',
]

from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import DeleteRequest as DeleteSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.chromite.api.test import ChromiteUnitTestRequest


def RunSteps(api):
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context(), \
    api.cros_sdk.cleanup_context(
        checkout_path=api.cros_source.workspace_path):
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.sync_gitiles_snapshot(api.buildbucket.gitiles_commit)

      gerrit_changes = api.buildbucket.build.input.gerrit_changes
      if gerrit_changes:
        with api.step.nest('cherry-pick gerrit changes'):
          patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
          api.cros_source.apply_gerrit_patch_sets(patch_sets)

      with api.step.nest('init sdk') as step:
        try:
          api.cros_sdk.build_chmod_chroot()
          response = api.cros_build_api.SdkService.Create(
              CreateSdkRequest(
                  flags=CreateSdkRequest.Flags(no_replace=True,
                                               no_use_image=True),
                  chroot=api.cros_sdk.chroot))
          step.presentation.logs['sdk version'] = [
              str(response.version.version)
          ]
          api.cros_sdk.link_chroot(api.cros_source.workspace_path)
        except api.step.StepFailure as e:
          # Invalidate the cache if the InitSDK call fails.
          api.step.nest(
              'InitSDK failure, deleting chroot',
              api.cros_build_api.SdkService.Delete(
                  DeleteSdkRequest(chroot=api.cros_sdk.chroot)))
          raise

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
  yield api.test('no-gerrit-changes')

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

  yield (
      api.test('updatesdk-destroy-chroot-tests') +  #
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='chromite-cq') +  #
      api.step_data(
          'update sdk.call chromite.api.SdkService/Update.call build API script',
          retcode=1))
