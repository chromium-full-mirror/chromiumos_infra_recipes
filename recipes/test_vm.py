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

import os

from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.chromiumos.common import Path
from PB.chromite.api.sdk import CreateRequest as CreateSdkRequest
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
    'recipe_engine/cq',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'failures',
    'gerrit',
]

PROPERTIES = TestVmProperties


PRIVATE_KEY_NAME = 'id_rsa'
VM_IMAGE_NAME = 'chromiumos_qemu_image.bin'


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
        gerrit_changes = api.cq.ordered_gerrit_changes
        with api.step.nest('cherry-pick gerrit changes'):
          patch_sets = api.gerrit.fetch_patch_sets(gerrit_changes)
          api.cros_source.apply_gerrit_patch_sets(patch_sets)

    api.cros_build_api.SdkService.Create(
        CreateSdkRequest(
            flags=CreateSdkRequest.Flags(no_replace=True, no_use_image=True),
            chroot=api.cros_sdk.chroot), name='init sdk')

    api.cros_build_api.SdkService.Update(
        UpdateSdkRequest(chroot=api.cros_sdk.chroot,
                         toolchain_targets=[properties.build_target]),
        name='update sdk')

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
      with api.step.nest('build autotest packages'):
        sysroot = api.cros_build_api.SysrootService.Create(
            SysrootCreateRequest(
                build_target=properties.build_target,
                chroot=api.cros_sdk.chroot,
                flags=SysrootCreateRequest.Flags(chroot_current=True)),
            name='create sysroot').sysroot

        failed_packages = api.cros_build_api.SysrootService.InstallToolchain(
            InstallToolchainRequest(sysroot=sysroot,
                                    chroot=api.cros_sdk.chroot),
            name='install toolchain').failed_packages
        api.failures.raise_failed_packages(failed_packages)

        failed_packages = api.cros_build_api.SysrootService.InstallPackages(
            InstallPackagesRequest(
                sysroot=sysroot,
                chroot=api.cros_sdk.chroot,
                packages=[PackageInfo(category='chromeos-base',
                                      package_name='autotest-all')]),
            name='install packages').failed_packages
        api.failures.raise_failed_packages(failed_packages)

    # TODO(evanhernandez): Read and present the test results.
    api.cros_build_api.TestService.VmTest(
        VmTestRequest(
            build_target=properties.build_target, chroot=api.cros_sdk.chroot,
            vm_path=Path(path=vm_image_path, location=Path.OUTSIDE),
            ssh_options=VmTestRequest.SshOptions(
                private_key_path=private_key_path),
            test_harness=properties.test_harness, vm_tests=[
                VmTestRequest.VmTest(pattern=exp)
                for exp in properties.expressions
            ]), name='run tast vm tests')


def GenTests(api):
  yield (api.test('with-tast') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +  #
         api.cq(full_run=True) +  #
         api.properties(
             build_target={'name': 'amd64-generic'},
             test_harness=VmTestRequest.TAST, build_payload={
                 'artifacts_gs_bucket': 'gs://chromeos-image-archive',
                 'artifacts_gs_path': 'amd64-generic-cq/R12-3.4.5-6',
             }, expressions=['example.Pass']))

  yield (api.test('with-autotest') +  #
         api.buildbucket.try_build(project='chromeos', bucket='cq',
                                   builder='amd64-generic-cq') +
         api.cq(full_run=True) +  #
         api.properties(
             build_target={'name': 'amd64-generic'},
             test_harness=VmTestRequest.AUTOTEST, build_payload={
                 'artifacts_gs_bucket': 'gs://chromeos-image-archive',
                 'artifacts_gs_path': 'amd64-generic-cq/R12-3.4.5-6',
             }, expressions=['example.Pass']))
