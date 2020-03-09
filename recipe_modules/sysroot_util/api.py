# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""


from recipe_engine import recipe_api

from PB.chromiumos.common import PrepareForBuildResponse


class SysrootUtilApi(recipe_api.RecipeApi):
  """A module for sysroot setup, manipulation, and use."""

  def initialize(self):
    self._sysroot = None

  @property
  def sysroot(self):
    return self._sysroot

  def update_for_artifact_build(self, artifacts, args, force_relevance=False):
    """Update ebuilds for artifact build.

    Args:
      artifacts (BuilderConfig.Artifacts): Artifact Information
      args (PrepareForBuild.AdditionalArgs): Parameters from config.
      force_relevance (bool): Whether to always claim relevant.

    Returns:
      (PrepareForBuildResponse): Whether the build is relevant.
    """
    # Prepare for the build.  If the build is pointless, we are done.
    resp = PrepareForBuildResponse.UNKNOWN
    if artifacts.artifact_types:
      # If there are artifacts, always call the Build API.
      resp = self.m.cros_artifacts.prepare_for_build(
          artifacts.artifact_types, self.m.chroot_util.chroot, self.sysroot,
          artifacts.input_artifacts, args)

    # If the build is POINTLESS, then we are done.  This can only happen if
    # all of the artifact_types for this build are handled by some
    # PrepareForBuild endpoint, and indicate that the build is pointless.
    #
    # If there are any artifact_types with no PrepareForBuild endpoint
    # defined, then resp will be UNKNOWN.
    if force_relevance:
      return PrepareForBuildResponse.NEEDED
    return resp
