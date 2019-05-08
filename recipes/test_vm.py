# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running Tast VM tests.

Because the scripts that run VM tests live within the build API,
this recipe does a lot of what build_target does. Namely, it syncs to the
snapshot used to build the test image, it applies gerrit patches, it inits
the SDK, etc.

The steps specific to VM testing are:
  1. Download the test image.
  2. Convert the test image to a VM. This happens here instead of build_target
     because most targets do not run VM tests.
  3. Call the build API to run VM tests.

For now, only supports TAST VM tests.
"""

from PB.chromiumos.common import BuildTarget
from PB.chromite.api.image import CreateVmRequest
from PB.chromite.api.image import Image
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.test import VmTestRequest
from PB.recipes.chromeos.test_vm import TestVmProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/archive',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'gerrit',
]

PROPERTIES = TestVmProperties


PRIVATE_KEY_NAME = 'id_rsa'
TEST_IMAGE_NAME = 'chromiumos_test_image.bin'

def RunSteps(api, properties):
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
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
      response = api.cros_build_api.SdkService.Create(
          CreateSdkRequest(
              flags=CreateSdkRequest.Flags(no_replace=True, no_use_image=True),
              chroot=api.cros_sdk.chroot))
      step.presentation.logs['sdk version'] = [str(response.version.version)]

    with api.step.nest('download test image'):
      test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
      test_image_zip = test_artifacts_dir.join('image.zip')
      test_image_dir = test_artifacts_dir.join('image')
      api.gsutil.download(properties.image_zip.gs_bucket,
                          properties.image_zip.gs_path, test_image_zip,
                          name='download image bundle from GS')
      api.archive.extract('unzip image bundle',
                          test_image_zip, test_image_dir,
                          include_files=[TEST_IMAGE_NAME, PRIVATE_KEY_NAME])
      test_image_path = str(test_image_dir.join(TEST_IMAGE_NAME))
      private_key_path = str(test_image_dir.join(PRIVATE_KEY_NAME))

    with api.step.nest('convert test image to vm image'):
      create_vm_response = api.cros_build_api.ImageService.CreateVm(
          CreateVmRequest(
              image=Image(build_target=properties.build_target,
                          path=test_image_path, type=Image.TEST),
              chroot=api.cros_sdk.chroot))

    with api.step.nest('run tast vm tests'):
      # TODO(evanhernandez): Read and present the test results.
      api.cros_build_api.TestService.VmTest(
          VmTestRequest(
              build_target=properties.build_target,
              chroot=api.cros_sdk.chroot,
              vm_image=create_vm_response.vm_image,
              ssh_options=VmTestRequest.SshOptions(
                  private_key_path=private_key_path),
              test_harness=VmTestRequest.TAST,
              vm_tests=[VmTestRequest.VmTest(pattern=exp)
                        for exp in properties.expressions]))


def GenTests(api):
  yield (api.test('with-gerrit-changes') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +
         api.properties(build_target={'name': 'amd64-generic'},
                        image_zip={
                            'gs_bucket': 'gs://chromeos-image-archive',
                            'gs_path': 'amd64-generic-cq/R12-3.4.5-6/image.zip',
                        },
                        expressions=['example.Pass']))
