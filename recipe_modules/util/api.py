# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module providing importable utilities.

"""

from typing import Optional

from PB.chromiumos import common as common_pb2
from recipe_engine import config_types
from recipe_engine import recipe_api


class UtilApi(recipe_api.RecipeApi):
  """Includable utilities."""

  def proto_path_to_recipes_path(
      self, proto_path: common_pb2.Path,
      chroot_path: Optional[config_types.Path] = None) -> config_types.Path:
    """Return a config_types.Path equivalent to the common_pb2.Path.

    Args:
      proto_path: A Path proto message, as might be returned by the build API.
        Must be absolute, and location must be specified as either INSIDE or
        OUTSIDE.
      chroot_path: The path to the SDK checked out on this builder. Only
        required when converting an INSIDE path. Normally this path is accessed
        via self.m.cros_sdk.chroot_path. However, the `util` module
        intentionally doesn't depend on any ChromeOS modules, so we can't fetch
        it here.

    Raises:
      ValueError: If proto_path.location is OUTSIDE and proto_path.path is not
        relative to any recipe anchor point. See the path API for more info
        info about those anchor points. This exception is raised during
        self.m.path.abs_to_path().
      ValueError: If proto_path.location is INSIDE and chroot_path is not given.
      ValueError: If proto_path.location is INSIDE and proto_path.path is not
        relative to '/'.
      ValueError: If proto_path.location is not specified as either INSIDE or
        OUTSIDE.
    """
    if proto_path.location == common_pb2.Path.Location.OUTSIDE:
      return self.m.path.abs_to_path(proto_path.path)
    if proto_path.location == common_pb2.Path.Location.INSIDE:
      if not chroot_path:
        raise ValueError(
            f'Cannot convert inside path without chroot path: {proto_path}')
      if not proto_path.path.startswith('/'):
        raise ValueError(
            f'Cannot convert inside path not relative to "/": {proto_path}')
      relative_to_chroot = proto_path.path.lstrip('/')
      path_parts = relative_to_chroot.split('/')
      return chroot_path.join(*path_parts)
    raise ValueError(
        f'Cannot process path with unspecified location: {proto_path}')
