# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for running VM tests.

Because the scripts that run VM tests live within the build API,
this recipe does a lot of what build_target does. Namely, it syncs to the
snapshot used to build the test image, it applies gerrit patches, it inits
the SDK, etc.

The steps specific to VM testing are:
  1. Setup workspace so it aligns with the workspace in which the image was
     build, i.e. sync to snapshot, apply gerrit changes, init/upate SDK, etc.
  2. Download the test image.
  3. If the VM tests run within the autotest harness, build autotest.
  4. Call the build API to run VM tests.
"""

import os

from PB.chromiumos.common import PackageInfo
from PB.chromiumos.common import Path
from PB.chromite.api.test import VmTestRequest
from PB.recipes.chromeos.test_vm import TestVmProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/archive',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'test_util',
]

PROPERTIES = TestVmProperties

PRIVATE_KEY_NAME = 'id_rsa'
VM_IMAGE_NAME = 'chromiumos_qemu_image.bin'


def RunSteps(api, properties):

  # Ensure that the workspace aligns with the image that was built.
  # Though this seems wasteful, it will catch bugs introduced to the build
  # API and any scripts it depends on.
  with api.build_menu.configure_builder(missing_ok=True), \
      api.build_menu.setup_workspace_and_chroot():
    return DoRunSteps(api, properties)


def DoRunSteps(api, properties):
  # We expect that we do not have a config, but we do have some non-default
  # values.  In the event that a config _IS_ present, let that win.
  config = api.build_menu.config_or_default

  with api.step.nest('download vm image'):
    test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
    test_image_zip = test_artifacts_dir.join('image.zip')
    test_image_dir = test_artifacts_dir.join('image')
    api.gsutil.download(
        properties.build_payload.artifacts_gs_bucket,
        os.path.join(properties.build_payload.artifacts_gs_path, 'image.zip'),
        test_image_zip, name='download image bundle from GS')
    api.archive.extract('unzip image bundle', test_image_zip, test_image_dir,
                        include_files=[VM_IMAGE_NAME, PRIVATE_KEY_NAME])
    vm_image_path = str(test_image_dir.join(VM_IMAGE_NAME))
    private_key_path = str(test_image_dir.join(PRIVATE_KEY_NAME))

  # Autotest assumes all the files it needs exist in the sysroot.
  # Rather than hack the prebuilts into the sysroot, just rebuild.
  # TODO(evanhernandez): Find a way to stop doing this. It's wasteful.
  if properties.test_harness == VmTestRequest.AUTOTEST:
    with api.step.nest('build autotest packages') as bap_pres:

      packages = [
          PackageInfo(category='chromeos-base', package_name='autotest-all')
      ]
      api.build_menu.setup_sysroot_and_determine_relevance(packages=packages)
      api.build_menu.bootstrap_sysroot_and_install_packages(config, packages)

  # TODO(evanhernandez): Read and present the test results.
  test_harness_name = VmTestRequest.TestHarness.Name(properties.test_harness)
  api.cros_build_api.TestService.VmTest(
      VmTestRequest(
          build_target=api.build_menu.build_target, chroot=api.cros_sdk.chroot,
          vm_path=Path(path=vm_image_path, location=Path.OUTSIDE),
          ssh_options=VmTestRequest.SshOptions(
              private_key_path=Path(path=private_key_path,
                                    location=Path.OUTSIDE)),
          test_harness=properties.test_harness, vm_tests=[
              VmTestRequest.VmTest(pattern=exp)
              for exp in properties.expressions
          ]), name='run %s vm tests' % test_harness_name.lower(),
      timeout=90 * 60)


def GenTests(api):
  yield api.test(
      'with-tast',
      api.test_util.test_child_build('amd64-generic', cq=True,
                                     builder='amd64-generic-autotest-vm').build,
      api.properties(
          test_harness=VmTestRequest.TAST, build_payload={
              'artifacts_gs_bucket': 'gs://chromeos-image-archive',
              'artifacts_gs_path': 'amd64-generic-cq/R12-3.4.5-6',
          }, expressions=['example.Pass']),
  )

  yield api.test(
      'with-autotest',
      api.test_util.test_child_build('amd64-generic', cq=True,
                                     builder='amd64-generic-autotest-vm').build,
      api.properties(
          test_harness=VmTestRequest.AUTOTEST, build_payload={
              'artifacts_gs_bucket': 'gs://chromeos-image-archive',
              'artifacts_gs_path': 'amd64-generic-cq/R12-3.4.5-6',
          }, expressions=['example.Pass']),
  )
