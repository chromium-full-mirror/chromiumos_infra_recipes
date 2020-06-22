# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing Chrome OS recipes.

This module provides helpers to make testing Chrome OS recipes simpler and more
consistent.
"""
from recipe_engine import recipe_test_api
from PB.recipes.chromeos.orchestrator import OrchestratorProperties


class OrchMenuTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing Chrome OS Recipes."""

  def test(self, name, *args, **kwargs):
    """A test, with orchestrator and OrchestratorProperties,

    This function creates a test orchestrator from kwargs, and then calls
    api.test() to create the TestData for a test.

    Default input properties are provided.

    Args:
      *args (list):  Arguments to pass to test_api.test.
      kwargs (dict): Arguments to pass to test_util.test_build.

    Returns:
      (recipe_test_api.TestData) TestData for the test.
    """
    kwargs.setdefault(
        'input_properties',
        OrchestratorProperties(
            update_manifest_refs=OrchestratorProperties.UpdateManifestRefs(
                start='refs/heads/postsubmit')))
    ret = self.m.test_util.test_orchestrator(**kwargs).build
    # Call recipe_test_api.test().
    return super(OrchMenuTestApi, self).test(name, ret, *args)
