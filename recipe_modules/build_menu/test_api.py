# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing Chrome OS recipes.

This module provides helpers to make testing Chrome OS recipes simpler and more
consistent.
"""
from recipe_engine import recipe_test_api

from PB.testplans.pointless_build import PointlessBuildCheckResponse


class BuildMenuTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing Chrome OS Recipes."""

  def depgraph_relevance_return(self, step, pointless):
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = pointless
    return self.step_data(
        '%s.read output file' % step,
        self.m.file.read_raw(content=resp.SerializeToString()))

  def set_pointless_return(self, value):
    return self.depgraph_relevance_return(
        'pointless build check.depgraph relevance check', value)

  def set_toolchain_cls_return(self, value):
    return self.depgraph_relevance_return(
        'init sdk.detect toolchain change.path relevancy check', not value)

  def set_build_api_return(self, step, endpoint, data, iteration=1):
    """Set the return from a Build API call.

    Args:
      step (str): Name of the step, such as 'prepare artifacts'.
      endpoint (str): Endpoint name, such as 'ImageService/Create'
      data (str): Build API response to return (JSON string).
      iteration (int): Which call this applies to for this step/endpoint.

    Returns:
      Step_data for the test.
    """
    return self.m.cros_build_api.set_api_return(step, endpoint, data, iteration)
