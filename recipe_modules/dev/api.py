# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for development config."""

from recipe_engine import recipe_api


class DevApi(recipe_api.RecipeApi):
  """A module for development config."""

  def __init__(self, *args, **kwargs):
    super(DevApi, self).__init__(*args, **kwargs)
    self._dryrun = False

  def configure(self, dryrun=None):
    """Configure the dev module.

    Args:
      * dryrun (bool): If True, run all module in a dryrun mode.
    """
    if dryrun is not None:
      self._dryrun = dryrun

  @property
  def dryrun(self):
    return self._dryrun
