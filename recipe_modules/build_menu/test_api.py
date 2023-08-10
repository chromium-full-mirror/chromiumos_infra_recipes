# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing Chrome OS recipes.

This module provides helpers to make testing Chrome OS recipes simpler and more
consistent.
"""

import re
from typing import Optional

from PB.testplans.pointless_build import PointlessBuildCheckResponse
from recipe_engine import post_process
from recipe_engine import recipe_test_api


class BuildMenuTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing Chrome OS Recipes."""

  def depgraph_relevance_return(self, step, pointless):
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = pointless
    return self.step_data(
        '%s.read output file' % step,
        self.m.file.read_raw(content=resp.SerializeToString()))

  def set_pointless_return(self, value):
    return self.depgraph_relevance_return('cq relevance check', value)

  def set_toolchain_cls_return(self, value):
    return self.depgraph_relevance_return('init sdk.detect toolchain change',
                                          not value)

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

  def test(self, name, *args, **kwargs):  # pylint: disable=arguments-differ
    """A test, with build and BuildMenuProperties,

    This function creates a test child_build from kwargs, and then calls
    api.test() to create the TestData for a test.

    The following arguments are consumed by this method:
      build_target (str): The name of the build target.  Default: amd64-generic.
      artifact_pointless (bool): Whether the artifact prepare step replies
        POINTLESS.
      pointless (bool): The reply from the pointless build check.

    Args:
      name: The name of the test.
      *args (list):  Arguments to pass to test_api.test, besides the name of
        the test.
      kwargs (dict): Arguments to pass to test_util.test_build.

    Returns:
      (recipe_test_api.TestData) TestData for the test.
    """
    # The combination of *args and **kwargs above makes this the least messy way
    # to have our own parameters, with defaults.
    status = kwargs.pop('status', 'SUCCESS')
    build_target = kwargs.pop('build_target', 'amd64-generic')
    artifact_pointless = kwargs.pop('artifact_pointless', False)
    pointless = kwargs.pop('pointless', False)

    ret = self.m.test_util.test_child_build(build_target, **kwargs).build
    if artifact_pointless:
      ret += self.m.cros_artifacts.set_prepare_pointless(artifact_pointless)
    if pointless:
      ret += self.set_pointless_return(True)
    # Call recipe_test_api.test().
    return super().test(name, ret, *args, status=status)

  def _assert_step_uses_bazel_or_portage(
      self, parent_step: Optional[str], endpoint: str,
      bazel: bool) -> recipe_test_api.TestData:
    """Assert whether the given build API step uses Bazel or Portage.

    Args:
      parent_step: The name of the step which contains the Build API call, such
        as 'install packages'. If there is no parent step, then None or empty
        string is OK.
      endpoint: The name of the Build API endpoint (service and method) that can
        specify Bazel, such as 'SysrootService/InstallPackages'.
      bazel: If True, assert that Bazel is used. If False, assert that it isn't.

    Returns:
      A post_check assertion that can be included in your test case to assert
      that the step did (not) use Bazel.
    """
    assert re.match(r'^\w+Service\/\w+$', endpoint), \
        f'malformed endpoint "{endpoint}"―should look like "MyService/MyMethod"'
    # As of July 2023, for all Build API endpoints that can use either Portage
    # or Bazel, the default is Portage but this can be overridden by specifying
    # a bool in the request message, named 'bazel'.
    # Thus, we can assert that the request logs either contain, or do not
    # contain, the string literal '"bazel": true'.
    # For some endpoints, but not all, the flag is embedded in a nested message.
    # Thus, we can't specify the exact level of indentation.
    if bazel:
      checker = post_process.LogContains
    else:
      checker = post_process.LogDoesNotContain
    parent_step_prefix = f'{parent_step}.' if parent_step else ''
    step = f'{parent_step_prefix}call chromite.api.{endpoint}'
    return self.post_check(checker, step, 'request', ['"bazel": true'])

  def assert_step_uses_bazel(self, parent_step: Optional[str],
                             endpoint: str) -> recipe_test_api.TestData:
    """Assert that the given build API step uses Bazel.

    Args:
      parent_step: The name of the step which contains the Build API call, such
        as 'install packages'. If there is no parent step, then None or empty
        string is OK.
      endpoint: The name of the Build API endpoint (service and method) that can
        specify Bazel, such as 'SysrootService/InstallPackages'.

    Returns:
      A post_check assertion that can be included in your test case to assert
      that the step used Bazel.
    """
    return self._assert_step_uses_bazel_or_portage(parent_step, endpoint, True)

  def assert_step_uses_portage(self, parent_step: Optional[str],
                               endpoint: str) -> recipe_test_api.TestData:
    """Assert that the given build API step did not use Bazel.

    Args:
      parent_step: The name of the step which contains the Build API call, such
        as 'install packages'. If there is no parent step, then None or empty
        string is OK.
      endpoint: The name of the Build API endpoint (service and method) that can
        specify Bazel, such as 'SysrootService/InstallPackages'.

    Returns:
      A post_check assertion that can be included in your test case to assert
      that the step used Portage.
    """
    return self._assert_step_uses_bazel_or_portage(parent_step, endpoint, False)
