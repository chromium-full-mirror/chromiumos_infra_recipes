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
