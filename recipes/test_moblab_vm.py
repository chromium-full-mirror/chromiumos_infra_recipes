# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running Moblab VM tests."""

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Path
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import DeleteRequest as DeleteSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.chromite.api.test import MoblabVmTestRequest
from PB.recipes.chromeos.test_moblab_vm import TestMoblabVmProperties

DEPS = [
    'recipe_engine/archive',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_artifacts',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'cros_test_plan',
    'gerrit',
]

PROPERTIES = TestMoblabVmProperties

# Artifacts that will be stored in the moblab image cache.
CACHE_ARTIFACTS = [
    BuilderConfig.Artifacts.TEST_UPDATE_PAYLOAD,
    BuilderConfig.Artifacts.AUTOTEST_FILES,
]

def RunSteps(api, properties):
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context(), \
    api.cros_sdk.cleanup_context(
        checkout_path=api.cros_source.workspace_path):
    # Ensure that the workspace aligns with the image that was built.
    # Though this seems wasteful, it will catch bugs introduced to the build
    # API and any scripts it depends on.
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
              UpdateSdkRequest(
                  chroot=api.cros_sdk.chroot,
                  toolchain_targets=[BuildTarget(name='moblab-generic-vm')]))
        except api.step.StepFailure:
          # Invalidate the cache if the UpdateSDK call fails.
          api.step.nest(
              'UpdateSDK failure, deleting chroot',
              api.cros_build_api.SdkService.Delete(
                  DeleteSdkRequest(chroot=api.cros_sdk.chroot)))
          raise

    with api.step.nest('prepare artifacts'):
      artifact_paths_by_artifact = api.cros_artifacts.download_artifacts(
          properties.build_payload,
          [BuilderConfig.Artifacts.IMAGE_ZIP] + CACHE_ARTIFACTS)

      with api.step.nest('inflate image bundle'):
        image_files = artifact_paths_by_artifact[
            BuilderConfig.Artifacts.IMAGE_ZIP]
        assert len(image_files) == 1, (
            'expected one image archive, got: %r' % image_files)
        image_zip = image_files[0]
        image_dir = api.path.mkdtemp(prefix='image-under-test-').join('image')
        api.archive.extract('unzip image.zip', image_zip, image_dir)

      with api.step.nest('group artifacts for moblab image cache'):
        moblab_cache_dir = api.path.mkdtemp(prefix='moblab-cache-artifacts-')
        for artifact in CACHE_ARTIFACTS:
          artifact_name = BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)
          artifact_paths = artifact_paths_by_artifact[artifact]
          for artifact_path in artifact_paths:
            api.file.copy('add %s to cache payload' % artifact_name,
                          artifact_path, moblab_cache_dir)

    def as_payload(path):
      return MoblabVmTestRequest.Payload(
          path=Path(path=str(path), location=Path.OUTSIDE))
    # TODO(evanhernandez): Read and present the test results.
    api.cros_build_api.TestService.MoblabVmTest(
        MoblabVmTestRequest(
            chroot=api.cros_sdk.chroot,
            image_payload=as_payload(image_dir),
            cache_payloads=[as_payload(moblab_cache_dir)]),
        name='run moblab vm tests',
    )

def GenTests(api):
  yield (api.test('basic') +
         # TODO(evanhernandez): Create a good fake config for moblab vm tests.
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +
         api.cq(full_run=True) +
         api.properties(
             name='moblab-vm-name',
             build_payload=api.cros_test_plan.test_unit_common().build_payload))

  yield (
      api.test('initsdk-destroy-chroot-tests') +  #
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='amd64-generic-cq') +  #
      api.step_data(
          'init sdk.call chromite.api.SdkService/Create.call build API script',
          retcode=1))

  yield (
      api.test('updatesdk-destroy-chroot-tests') +  #
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='amd64-generic-cq') +  #
      api.step_data(
          'update sdk.call chromite.api.SdkService/Update.call build API script',
          retcode=1))
