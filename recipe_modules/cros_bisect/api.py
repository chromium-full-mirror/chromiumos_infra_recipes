# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with FindIt."""

from recipe_engine import recipe_api

class CrosBisectApi(recipe_api.RecipeApi):
  """A module for interacting with FindIt."""

  def __init__(self, findit_bisect, *args, **kwargs):
    super(CrosBisectApi, self).__init__(*args, **kwargs)
    self._findit_bisect = findit_bisect

  def set_bisect_builder(self, build_target_name):
    """Sets the BISECT_BUILDER output property.

    Sets the BISECT_BUILDER output property to the name of the builder FindIt
    should invoke if the build fails and bisection is required.
    """
    res = self.m.step('set_bisect_builder', cmd=None)
    res.presentation.properties['BISECT_BUILDER'] = build_target_name + '-bisect'

  def get_packages(self):
    """Returns packages to build as specified by FindIt or empty list.

    Returns the packages to build as specified by a FindIt invocation or an
    empty list if this run was not invoked as a bisection build.
    """
    return self._findit_bisect.get('targets', [])
