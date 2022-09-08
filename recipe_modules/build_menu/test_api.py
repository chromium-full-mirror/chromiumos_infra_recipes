# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
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

  def set_build_api_return(self, step, endpoint, data='', iteration=1,
                           retcode=0):
    """Set the return from a Build API call.

    Args:
      step (str): Name of the step, such as 'prepare artifacts'.
      endpoint (str): Endpoint name, such as 'ImageService/Create'
      data (str): Build API response to return (JSON string).
      iteration (int): Which call this applies to for this step/endpoint.
      retcode (int): Return code for the Build API call.

    Returns:
      Step_data for the test.
    """
    return self.m.cros_build_api.set_api_return(step, endpoint, data, iteration,
                                                retcode)

  def test(self, name, *args, **kwargs):
    """A test, with build and BuildMenuProperties,

    This function creates a test child_build from kwargs, and then calls
    api.test() to create the TestData for a test.

    The following arguments are consumed by this method:
      build_target (str): The name of the build target.  Default: amd64-generic.
      artifact_pointless (bool): Whether the artifact prepare step replies
          POINTLESS.
      pointless (bool): The reply from the pointless build check.

    Args:
      *args (list):  Arguments to pass to test_api.test.
      kwargs (dict): Arguments to pass to test_util.test_build.

    Returns:
      (recipe_test_api.TestData) TestData for the test.
    """
    # The combination of *args and **kwargs above makes this the least messy way
    # to have our own parameters, with defaults.
    build_target = kwargs.pop('build_target', 'amd64-generic')
    artifact_pointless = kwargs.pop('artifact_pointless', False)
    pointless = kwargs.pop('pointless', False)

    ret = self.m.test_util.test_child_build(build_target, **kwargs).build
    if artifact_pointless:
      ret += self.m.cros_artifacts.set_prepare_pointless(artifact_pointless)
    if pointless:
      ret += self.set_pointless_return(True)
    # Call recipe_test_api.test().
    return super(BuildMenuTestApi, self).test(name, ret, *args)
