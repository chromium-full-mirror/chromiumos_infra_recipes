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
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_artifacts',
    'cros_build_api',
    'cros_sdk',
    'cros_test_plan',
    'gerrit',
    'test_util',
]

PROPERTIES = TestMoblabVmProperties

# Artifacts that will be stored in the moblab image cache.
CACHE_ARTIFACTS = [
    BuilderConfig.Artifacts.TEST_UPDATE_PAYLOAD,
    BuilderConfig.Artifacts.AUTOTEST_FILES,
]


def RunSteps(api, properties):

  with api.build_menu.configure_builder(missing_ok=True):
    return DoRunSteps(api, properties)


def DoRunSteps(api, properties):
  api.build_menu.setup_workspace_and_chroot(no_chroot_timeout=True)

  with api.step.nest('prepare artifacts'):
    artifact_paths_by_artifact = api.cros_artifacts.download_artifacts(
        properties.build_payload,
        [BuilderConfig.Artifacts.IMAGE_ZIP] + CACHE_ARTIFACTS)

    with api.step.nest('inflate image bundle'):
      image_files = artifact_paths_by_artifact[
          BuilderConfig.Artifacts.IMAGE_ZIP]
      assert len(image_files) == 1, ('expected one image archive, got: %r' %
                                     image_files)
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
      MoblabVmTestRequest(chroot=api.cros_sdk.chroot,
                          image_payload=as_payload(image_dir),
                          cache_payloads=[as_payload(moblab_cache_dir)]),
      name='run moblab vm tests',
  )


def GenTests(api):

  def test_build():
    return api.test_util.test_child_build(
        'moblab-generic-vm', builder='moblab-vm-test', cq=True,
        revision='0572e38c2b2073613ee5b861a9165335621bf54a').build

  yield api.test(
      'basic', test_build(),
      api.properties(
          name='moblab-vm-name',
          build_payload=api.cros_test_plan.test_unit_common().build_payload))

  yield api.test(
      'initsdk-destroy-chroot-tests', test_build(),
      api.cros_build_api.set_api_return('init sdk', 'SdkService/Create',
                                        retcode=1))

  yield api.test(
      'updatesdk-destroy-chroot-tests', test_build(),
      api.cros_build_api.set_api_return('update sdk', 'SdkService/Update',
                                        retcode=1))
