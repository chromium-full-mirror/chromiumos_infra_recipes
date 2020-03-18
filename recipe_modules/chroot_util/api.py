# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for various support functions for building."""

from recipe_engine import recipe_api


class ChrootUtilApi(recipe_api.RecipeApi):
  """A module for chroot (sdk) setup and manipulation."""

  def initialize(self):
    self._chroot = None

  @property
  def chroot(self):
    return self._chroot

  def init_sdk(self, version=None, use_image=True, timeout_sec=40 * 60,
               name=None):
    """Initialize the SDK.

    Args:
      version (int): Required SDK version, if any.  Some recipes do not care
          what version the SDK is, they just need any SDK.
      use_image (boolean): Mount the SDK file as an image. Default: True.
      timeout_sec (int): Step timeout (in seconds). Default: 40 * 60.
      name (string): Step name.  Default: "init sdk".

    Returns:
      chromiumos_pb2.Chroot protobuf for the initialized SDK.
    """
    self._chroot = self.m.cros_sdk.create_chroot(
        version=version, use_image=use_image, timeout_sec=timeout_sec,
        name=name)
    return self.chroot
