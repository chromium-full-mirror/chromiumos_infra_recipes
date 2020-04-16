# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

from recipe_engine import recipe_api

from PB.chromiumos.common import PrepareForBuildResponse
from PB.chromite.api.sysroot import Profile
from PB.chromite.api.sysroot import SysrootCreateRequest


class SysrootUtilApi(recipe_api.RecipeApi):
  """A module for sysroot setup, manipulation, and use."""

  def initialize(self):
    self._sysroot = None

  @property
  def sysroot(self):
    return self._sysroot

  def update_for_artifact_build(self, chroot, artifacts, args,
                                force_relevance=False, name=None):
    """Update ebuilds for artifact build.

    Args:
      chroot (Chroot): Chroot, or None.
      artifacts (BuilderConfig.Artifacts): Artifact Information
      args (PrepareForBuild.AdditionalArgs): Parameters from config.
      force_relevance (bool): Whether to always claim relevant.
      name (str): Step name to use, or None for default name.

    Returns:
      (PrepareForBuildResponse): Whether the build is relevant.
    """
    # Prepare for the build.  If the build is pointless, we are done.
    resp = PrepareForBuildResponse.UNKNOWN
    if artifacts.artifact_types:
      # If there are artifacts, always call the Build API.
      resp = self.m.cros_artifacts.prepare_for_build(
          artifacts.artifact_types, chroot, self.sysroot,
          artifacts.input_artifacts, artifacts.artifact_profile_info, args,
          name=name)

    # If the build is POINTLESS, then we are done.  This can only happen if
    # all of the artifact_types for this build are handled by some
    # PrepareForBuild endpoint, and indicate that the build is pointless.
    #
    # If there are any artifact_types with no PrepareForBuild endpoint
    # defined, then resp will be UNKNOWN.
    if force_relevance:
      return PrepareForBuildResponse.NEEDED
    return resp

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
