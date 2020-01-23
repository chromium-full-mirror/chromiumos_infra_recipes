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

from PB.chromite.api.binhost import OVERLAYTYPE_BOTH
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.chromiumos.common import Path
from PB.chromiumos.common import UseFlag
from PB.chromite.api.packages import UprevPackagesRequest
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
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'chrome',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'failures',
    'gerrit',
    'goma',
]

PROPERTIES = TestVmProperties


PRIVATE_KEY_NAME = 'id_rsa'
VM_IMAGE_NAME = 'chromiumos_qemu_image.bin'


def RunSteps(api, properties):
  with api.cros_source.checkout_overlays_context(), \
    api.cros_sdk.cleanup_context(
        checkout_path=api.cros_source.workspace_path):
    # Ensure that the workspace aligns with the image that was built.
    # Though this seems wasteful, it will catch bugs introduced to the build
    # API and any scripts it depends on.
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache()
      api.cros_source.sync_snapshot(api.buildbucket.gitiles_commit)
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

      with api.step.nest('uprev packages') as step:
        request = UprevPackagesRequest(
            chroot=api.cros_sdk.chroot,
            build_targets=[BuildTarget(name=properties.build_target.name)],
            overlay_type=OVERLAYTYPE_BOTH)
        response = api.cros_build_api.PackageService.Uprev(request)

      with api.step.nest('update sdk'):
        try:
          api.cros_build_api.SdkService.Update(
              UpdateSdkRequest(
                  chroot=api.cros_sdk.chroot, toolchain_targets=[
                      BuildTarget(name=properties.build_target.name)
                  ]))
        except api.step.StepFailure:
          # Invalidate the cache if the UpdateSDK call fails.
          api.step.nest(
              'UpdateSDK failure, deleting chroot',
              api.cros_build_api.SdkService.Delete(
                  DeleteSdkRequest(chroot=api.cros_sdk.chroot)))
          raise

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
      with api.step.nest('build autotest packages') as bap_step:
        sysroot = api.cros_build_api.SysrootService.Create(
            SysrootCreateRequest(
                build_target=properties.build_target,
                chroot=api.cros_sdk.chroot,
                flags=SysrootCreateRequest.Flags(chroot_current=True,
                                                 replace=True)),
            name='create sysroot').sysroot

        failed_packages = api.cros_build_api.SysrootService.InstallToolchain(
            InstallToolchainRequest(sysroot=sysroot,
                                    chroot=api.cros_sdk.chroot),
            name='install toolchain').failed_packages
        api.failures.set_failed_packages(bap_step, failed_packages)

        # TODO(crbug.com/1011011): sync and goma build chrome if needed
        # because Autotest VM builders are rebuilding chrome.
        if api.chrome.builds_chrome_from_source(properties.build_target,
                                                api.cros_sdk.chroot,
                                                internal=True):
          chrome_root = api.path['start_dir'].join('chrome')
          # Internal or external chrome? In build_target.py we take this
          # from build_config.chrome.internal. Also forced True in the
          # builds_chrome_from_source call above to match the force True here.
          chrome_internal = True
          api.chrome.sync(chrome_root, api.cros_sdk.chroot,
                          properties.build_target, chrome_internal)
          api.cros_sdk.set_chrome_root(str(chrome_root))
          api.cros_sdk.set_goma_config(
              str(api.goma.goma_dir),
              str(api.goma.goma_client_json),
              api.goma.goma_approach,
              str(api.path.mkdtemp(prefix='goma-logs-')),
              'stats.binaryproto',
              'counterz.binaryproto')

        flags = InstallPackagesRequest.Flags(
            compile_source=False,
            use_goma=api.cros_sdk.has_goma_config())
        packages = [PackageInfo(category='chromeos-base',
                                package_name='autotest-all')]
        # Matching chrome_internal = True above.
        # In build_target.py we take this from build_config.build.use_flags.
        use_flags = [UseFlag(flag='chrome_internal')]
        failed_packages = api.cros_build_api.SysrootService.InstallPackages(
            InstallPackagesRequest(
                sysroot=sysroot,
                flags=flags,
                chroot=api.cros_sdk.chroot,
                packages=packages,
                use_flags=use_flags,
                goma_config=api.cros_sdk.goma_config()),
            name='install packages').failed_packages
        # TODO: if used goma, emit goma info, stats, counterz.
        api.failures.set_failed_packages(bap_step, failed_packages)

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
  yield (api.test('with-tast') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.properties(
             build_target={'name': 'amd64-generic'},
             test_harness=VmTestRequest.TAST, build_payload={
                 'artifacts_gs_bucket': 'gs://chromeos-image-archive',
                 'artifacts_gs_path': 'amd64-generic-cq/R12-3.4.5-6',
             }, expressions=['example.Pass']))

  yield (api.test('with-autotest') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +
         api.properties(
             build_target={'name': 'amd64-generic'},
             test_harness=VmTestRequest.AUTOTEST, build_payload={
                 'artifacts_gs_bucket': 'gs://chromeos-image-archive',
                 'artifacts_gs_path': 'amd64-generic-cq/R12-3.4.5-6',
             }, expressions=['example.Pass']))

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
