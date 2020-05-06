# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

from recipe_engine import recipe_api

from PB.chromite.api.artifacts import PrepareForBuildResponse
from PB.chromite.api.sysroot import Profile
from PB.chromite.api.sysroot import SysrootCreateRequest


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
      name (str): Step name to use, or None for default name.

    Returns:
      (PrepareForBuildResponse): Whether the build is relevant.
    """
    # Prepare for the build.  If the build is pointless, we are done.
    resp = self.m.cros_artifacts.prepare_for_build(
        chroot, self.sysroot, artifacts.artifacts_info, force_relevance,
        test_data=test_data, name=name)

    # If the build is POINTLESS, then we are done.  This can only happen if
    # all of the artifact_types for this build are handled by some
    # PrepareForBuild endpoint, and indicate that the build is pointless.
    #
    # If there are any artifact_types with no PrepareForBuild endpoint
    # defined, then resp will be UNKNOWN.
    return PrepareForBuildResponse.NEEDED if force_relevance else resp

  def create_sysroot(self, build_target, profile=None, chroot_current=True,
                     replace=True, toolchain_changed=False, timeout_sec=10 * 60,
                     name=None):
    """Create the sysroot.

    Args:
      build_target (BuildTarget): Which build_target to create a sysroot for.
      profile (str): The name of the sysroot profile to use, or None.
      chroot_current (bool): Whether the chroot is current.  (If not, it will be
          updated.
      replace (bool): Whether to replace an existing sysroot.
      toolchain_changed (bool): Whether a toolchain change has occurred.
      timeout_sec (int): Step timeout, in seconds.
      name (str): Step name to use, or None for the default name.

    Returns:
      Sysroot
    """
    with self.m.step.nest(name or 'create sysroot'):
      profile = Profile(name=profile) if profile else None
      flags = SysrootCreateRequest.Flags(chroot_current=chroot_current,
                                         replace=replace,
                                         toolchain_changed=toolchain_changed)
      create_sysroot_response = self.m.cros_build_api.SysrootService.Create(
          SysrootCreateRequest(build_target=build_target, profile=profile,
                               chroot=self.m.cros_sdk.chroot, flags=flags),
          timeout=timeout_sec)
      self._sysroot = create_sysroot_response.sysroot
      return self.sysroot
