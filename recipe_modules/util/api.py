# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module providing importable utilities.

"""

from PB.chromiumos import common as common_pb2
from recipe_engine import config_types
from recipe_engine import recipe_api


class UtilApi(recipe_api.RecipeApi):
  """Includable utilities."""

  def proto_path_to_recipes_path(
      self, proto_path: common_pb2.Path) -> config_types.Path:
    """Return a config_types.Path equivalent to the common_pb2.Path.

    Args:
      proto_path: A Path proto message, as might be returned by the build API.
        Must be absolute, and location must be specified as either INSIDE or
        OUTSIDE.

    Raises:
      ValueError: If proto_path.location is OUTSIDE and proto_path.path is not
        relative to any recipe anchor point. See the path API for more info
        info about those anchor points. This exception is raised during
        self.m.path.abs_to_path().
      ValueError: If proto_path.location is INSIDE. Chroot paths are migrated
        to different outside locations according to Chromite logic that is
        subject to change. We deliberately do not replicate that logic here.
        Instead, if a recipe needs to reference INSIDE paths returned by a build
        API endpoint, the endpoint should be return OUTSIDE paths.
        If you need to refactor in this way, consider using the build API's
        ResultPath functionality for this. Add a ResultPath field to the
        request message, and ensure that the endpoint runs inside the chroot
        via either service_chroot_assert or method_chroot_assert. The API
        router will automatically extract any Path (or repeated Path) fields
        to the given ResultPath.
      ValueError: If proto_path.location is not specified (i.e. NO_LOCATION).
    """
    if proto_path.location == common_pb2.Path.Location.OUTSIDE:
      return self.m.path.abs_to_path(proto_path.path)
    if proto_path.location == common_pb2.Path.Location.INSIDE:
      raise ValueError(
          "Cannot convert INSIDE path. See this function's docstring for "
          f'suggestions. {proto_path}')
    raise ValueError(
        f'Cannot process path with unspecified location: {proto_path}')
