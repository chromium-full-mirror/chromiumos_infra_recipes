# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

from recipe_engine import recipe_api

from google.protobuf import json_format

from PB.chromite.api.artifacts import PrepareForBuildResponse
from PB.chromite.api.image import CreateImageRequest
from PB.chromite.api.image import CreateImageResult
from PB.chromite.api.image import Image
from PB.chromite.api.image import TestImageRequest
from PB.chromite.api.sysroot import InstallToolchainRequest
from PB.chromite.api.sysroot import Profile
from PB.chromite.api.sysroot import Sysroot
from PB.chromite.api.sysroot import SysrootCreateRequest
from PB.chromite.api.sysroot import SysrootCreateResponse
from PB.chromiumos.common import BASE
from PB.chromiumos.common import ImageType


class SysrootUtilApi(recipe_api.RecipeApi):
  """A module for sysroot setup, manipulation, and use."""

  def initialize(self):
    self._sysroot = None

  @property
  def sysroot(self):
    return self._sysroot

  def update_for_artifact_build(self, chroot, artifacts, force_relevance=False,
                                test_data=None, name=None):
    """Update ebuilds for artifact build.

    Args:
      chroot (Chroot): Chroot, or None.
      artifacts (BuilderConfig.Artifacts): Artifact Information
      force_relevance (bool): Whether to always claim relevant.
      test_data (str): test response (JSON) from the
          ArtifactsService/PrepareForBuild call, or None.
      name (str): Step name to use, or None for default name.

    Returns:
      (PrepareForBuildResponse): Whether the build is relevant.
    """
    # Prepare for the build.  If the build is pointless, we are done.
    resp = self.m.cros_artifacts.prepare_for_build(chroot, self.sysroot,
                                                   artifacts.artifacts_info,
                                                   force_relevance,
                                                   test_data=test_data,
                                                   name=name)

    # If the build is POINTLESS, then we are done.  This can only happen if
    # all of the artifact_types for this build are handled by some
    # PrepareForBuild endpoint, and indicate that the build is pointless.
    #
    # If there are any artifact_types with no PrepareForBuild endpoint
    # defined, then resp will be UNKNOWN.
    return PrepareForBuildResponse.NEEDED if force_relevance else resp

  def create_sysroot(self, build_target, profile=None, chroot_current=True,
                     replace=True, timeout_sec='DEFAULT', test_data=None,
                     name=None):
    """Create the sysroot.

    Args:
      build_target (BuildTarget): Which build_target to create a sysroot for.
      profile (str): The name of the sysroot profile to use, or None.
      chroot_current (bool): Whether the chroot is current.  (If not, it will be
          updated.
      replace (bool): Whether to replace an existing sysroot.
      timeout_sec (int): Step timeout (in seconds).  Default: None if a
          toolchain change is detected, otherwise 10 minutes.
      test_data (str): test response (JSON) from the SysrootService/Create
          call, or None to generate a default response based on the input data.
      name (str): Step name to use, or None for the default name.

    Returns:
      Sysroot
    """
    test_data = test_data or json_format.MessageToJson(
        SysrootCreateResponse(
            sysroot=Sysroot(path='/build/%s' %
                            build_target.name, build_target=build_target)))
    if timeout_sec == 'DEFAULT':
      timeout_sec = None if self.m.cros_sdk.long_timeouts else 10 * 60

    toolchain_cls = self.m.workspace_util.toolchain_cls_applied
    with self.m.step.nest(name or 'create sysroot'):
      profile = Profile(name=profile) if profile else None
      flags = SysrootCreateRequest.Flags(chroot_current=chroot_current,
                                         replace=replace,
                                         toolchain_changed=toolchain_cls)
      create_sysroot_response = self.m.cros_build_api.SysrootService.Create(
          SysrootCreateRequest(build_target=build_target, profile=profile,
                               chroot=self.m.cros_sdk.chroot, flags=flags),
          timeout=timeout_sec, test_output_data=test_data)
      self._sysroot = create_sysroot_response.sysroot
      return self.sysroot

  def bootstrap_sysroot(self, compile_source=False, response_lambda=None,
                        timeout_sec='DEFAULT', test_data=None, name=None):
    """Bootstrap the sysroot by calling InstallToolchain.

    Args:
      compile_source (bool): Whether to compile from source.
      response_lambda (fn(output_proto)->str): A function that appends a string
          to the build api response step. Used to make failure step names unique
          across differing root causes.  Default:
          cros_build_api.failed_pkg_names.
      timeout_sec (int): Step timeout, in seconds, or None for default.
      test_data (str): test response (JSON) from the
          SysrootService/InstallToolchain call, or None to use the default in
          cros_build_api/test_api.py.
      name (str): Step name to use, or None for the default name.
    """
    # If no timeout was given, it is either unlimited, or 30 minutes.
    if timeout_sec == 'DEFAULT':
      timeout_sec = None if self.m.cros_sdk.long_timeouts else 30 * 60
    response_lambda = response_lambda or self.m.cros_build_api.failed_pkg_names

    flags = InstallToolchainRequest.Flags(
        compile_source=compile_source,
        toolchain_changed=self.m.workspace_util.toolchain_cls_applied)

    with self.m.step.nest(name or 'install toolchain') as pres:
      response = self.m.cros_build_api.SysrootService.InstallToolchain(
          InstallToolchainRequest(sysroot=self.sysroot,
                                  chroot=self.m.cros_sdk.chroot, flags=flags),
          response_lambda=response_lambda, timeout=timeout_sec,
          test_output_data=test_data)
      self.m.failures.set_failed_packages(pres, response.failed_packages)

  def build_images(self, image_types, builder_path, disable_rootfs_verification,
                   disk_layout, timeout_sec=45 * 60, build_test_data=None,
                   test_test_data=None, name=None):
    """Build and validate images.

    Args:
      image_types (list[ImageType]): Image types to build.
      builder_path (str): Builder path in GS for artifacts.
      disable_rootfs_verification (bool): whether to disable rootfs verification.
      disk_layout (str): disk_layout to set, or empty for a sane default.
      timeout_sec (int): Step timeout (in seconds).
      build_test_data (str): test response (JSON) from the ImageService/Create
          call, or None.
      test_test_data (str): test response (JSON) from the ImageService/Test
          call, or None.
      name (str): name for the step.
    """
    if image_types:
      build_test_data = build_test_data or json_format.MessageToJson(
          CreateImageResult(
              success=True, images=[
                  Image(
                      type=x, path=str(self.m.path['start_dir'].join(
                          '/build/images/%s.bin' % ImageType.Name(x).lower())),
                      build_target=self.sysroot.build_target)
                  for x in image_types
              ]))
      with self.m.step.nest(name or 'build images') as pres:
        response = self.m.cros_build_api.ImageService.Create(
            CreateImageRequest(
                build_target=self.sysroot.build_target,
                chroot=self.m.cros_sdk.chroot,
                image_types=image_types,
                builder_path=builder_path,
                disable_rootfs_verification=disable_rootfs_verification,
                disk_layout=disk_layout,
            ), timeout=timeout_sec,
            response_lambda=self.m.cros_build_api.failed_pkg_names,
            test_output_data=build_test_data)
        self.m.failures.set_failed_packages(pres, response.failed_packages)

        to_test = [image for image in response.images if image.type == BASE]
        if BASE not in image_types or not to_test:
          # For now, as in legacy CQ, we only test base images. Images created
          # as a sideeffect (not explicitly requested in image_types) are not
          # tested.
          return

        with self.m.step.nest('test images'):
          failed_images = []
          for image in to_test:
            result_dir = self.m.path.mkdtemp(prefix='image-test-result-')
            if not self.m.cros_build_api.ImageService.Test(
                TestImageRequest(
                    image=image, build_target=self.sysroot.build_target,
                    result=TestImageRequest.Result(directory=str(result_dir)),
                    chroot=self.m.cros_sdk.chroot),
                test_output_data=test_test_data).success:
              failed_images.append(image)
          self.m.failures.raise_failed_image_tests(failed_images)
