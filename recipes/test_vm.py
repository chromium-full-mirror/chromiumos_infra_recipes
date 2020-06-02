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

from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.chromiumos.common import Path
from PB.chromiumos.common import UseFlag
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
from PB.chromite.api.sdk import DeleteRequest as DeleteSdkRequest
from PB.chromite.api.sdk import UpdateRequest as UpdateSdkRequest
from PB.chromite.api.sysroot import SysrootCreateRequest
from PB.chromite.api.sysroot import InstallToolchainRequest
from PB.chromite.api.sysroot import InstallPackagesRequest
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
    'chrome',
    'cros_build_api',
    'cros_sdk',
    'failures',
    'goma',
    'test_util',
    'workspace_util',
]

PROPERTIES = TestVmProperties

PRIVATE_KEY_NAME = 'id_rsa'
VM_IMAGE_NAME = 'chromiumos_qemu_image.bin'


def RunSteps(api, properties):
  with api.build_menu.configure_builder(properties.build_target,
                                        missing_ok=True):
    # Ensure that the workspace aligns with the image that was built.
    # Though this seems wasteful, it will catch bugs introduced to the build
    # API and any scripts it depends on.
    api.build_menu.setup_workspace_and_chroot()

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
        sysroot = api.build_menu.sysroot

        failed_packages = api.cros_build_api.SysrootService.InstallToolchain(
            InstallToolchainRequest(sysroot=sysroot,
                                    chroot=api.cros_sdk.chroot),
            name='install toolchain').failed_packages
        api.failures.set_failed_packages(bap_pres, failed_packages)

        # Note: the dependency graph requires a sysroot prior to crrev.com/c/2197226.
        # TODO(crbug/1053703): After 2020-11-12, if there is no sysroot, that's ok.
        dep_graph = api.build_menu.dep_graph

        def _InstallPackagesRequest():
          """Helper to make InstallPackagesRequest."""
          return InstallPackagesRequest(
              chroot=api.cros_sdk.chroot, sysroot=sysroot, packages=packages,
              flags=InstallPackagesRequest.Flags(
                  compile_source=False, use_goma=api.cros_sdk.has_goma_config(),
                  toolchain_changed=api.workspace_util.toolchain_cls_applied),
              use_flags=[UseFlag(flag='chrome_internal')],
              goma_config=api.cros_sdk.goma_config())

        # TODO(crbug.com/1011011): sync and goma build chrome if needed
        # because Autotest VM builders are rebuilding chrome.
        with api.step.nest('check chrome source needed') as cs_pres:
          if api.chrome.needs_chrome_source(_InstallPackagesRequest(),
                                            dep_graph, cs_pres):

            chrome_root = api.path['start_dir'].join('chrome')
            # Internal or external chrome? In build_target.py we take this
            # from build_config.chrome.internal. Also forced True in the
            # builds_chrome_from_source call above to match the force True here.
            api.chrome.sync(chrome_root, api.cros_sdk.chroot,
                            properties.build_target, internal=True)
            api.cros_sdk.configure_goma(chrome_root)

        install_pkg_request = _InstallPackagesRequest()
        response = api.cros_build_api.SysrootService.InstallPackages(
            install_pkg_request, name='install packages')

        # Process goma response to upload logs, stats, and counterz.
        api.goma.process_artifacts(response,
                                   install_pkg_request.goma_config.log_dir.dir,
                                   properties.build_target.name)

        # Process goma reponse to upload logs, stats, and counterz.
        api.failures.set_failed_packages(bap_pres, response.failed_packages)

    # TODO(evanhernandez): Read and present the test results.
    test_harness_name = VmTestRequest.TestHarness.Name(properties.test_harness)
    api.cros_build_api.TestService.VmTest(
        VmTestRequest(
            build_target=properties.build_target, chroot=api.cros_sdk.chroot,
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
      api.test_util.test_build(cq=True).build,
      api.properties(
          build_target={'name': 'amd64-generic'},
          test_harness=VmTestRequest.TAST, build_payload={
              'artifacts_gs_bucket': 'gs://chromeos-image-archive',
              'artifacts_gs_path': 'amd64-generic-cq/R12-3.4.5-6',
          }, expressions=['example.Pass']),
  )

  yield api.test(
      'with-autotest',
      api.test_util.test_build(cq=True).build,
      api.properties(
          build_target={'name': 'amd64-generic'},
          test_harness=VmTestRequest.AUTOTEST, build_payload={
              'artifacts_gs_bucket': 'gs://chromeos-image-archive',
              'artifacts_gs_path': 'amd64-generic-cq/R12-3.4.5-6',
          }, expressions=['example.Pass']),
  )
