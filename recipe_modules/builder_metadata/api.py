# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf.json_format import MessageToJson

from recipe_engine import recipe_api

from PB.chromite.api.packages import GetBuilderMetadataRequest


class BuilderMetadataApi(recipe_api.RecipeApi):
  """A module to get builder metadata."""

  def __init__(self, *args, **kwargs):
    super(BuilderMetadataApi, self).__init__(*args, **kwargs)
    self._cached_metadata = None

  def look_up_builder_metadata(self, test_data=None):
    """Looks up builder metadata for the provided build_target.

    Builder metadata does not change within the lifecycle of a build, so
    builder metadata is looked up once and cached.

    Important - a prerequisite for this method being able to return builder
    metadata is that `install_packages` has already been called.

    Returns:
      builder_metadata proto describing build and model for the current target.
    """
    if not (test_data or self.m.build_menu.packages_installed):
      raise recipe_api.StepFailure(
          'packages must be installed before look_up_builder_metadata is called'
      )
    with self.m.step.nest('look up builder metadata') as presentation:
      if self._cached_metadata is None:
        presentation.step_text = ((
            'No builder metadata cached. Querying Build API PackageService/'
            'GetBuilderMetadata.'))
        self._cached_metadata = \
          self.m.cros_build_api.PackageService.GetBuilderMetadata(
            GetBuilderMetadataRequest(
                build_target=self.m.build_menu.build_target,
                chroot=self.m.cros_sdk.chroot))
      presentation.logs["builder_metadata"] = MessageToJson(
          self._cached_metadata)

      return self._cached_metadata
