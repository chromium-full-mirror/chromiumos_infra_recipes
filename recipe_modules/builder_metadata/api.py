# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from google.protobuf.json_format import MessageToDict

from recipe_engine import recipe_api

from PB.chromite.api.packages import GetBuilderMetadataRequest


class BuilderMetadataApi(recipe_api.RecipeApi):
  """A module to get builder metadata."""

  def __init__(self, *args, **kwargs):
    super(BuilderMetadataApi, self).__init__(*args, **kwargs)
    self._cached_metadata = None

  def look_up_builder_metadata(self):
    """Looks up builder metadata for the provided build_target.

    Builder metadata does not change within the lifecycle of a build, so
    builder metadata is looked up once and cached.

    Returns:
      builder_metadata proto describing build and model for the current target.
    """
    if not self.m.build_menu.packages_installed:
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
      # TODO(b/217973414): Replace with MessageToJson once we don't need to
      # fix the separator spacing between py2 and py3 MessageToJson.
      presentation.logs["builder_metadata"] = json.dumps(
          MessageToDict(self._cached_metadata), indent=2, sort_keys=True,
          separators=(',', ':'))

      return self._cached_metadata

  def get_models(self):
    """Finds all model names associated with the active build_target.

    Returns:
      List[str]: The names of all models used by this build target.
    """
    builder_metadata = self.look_up_builder_metadata()
    return [model.model_name for model in builder_metadata.model_metadata]
