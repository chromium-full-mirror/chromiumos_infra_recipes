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
      *args (list): Arguments to pass to test_api.test.
      kwargs (dict): Arguments to pass to test_util.test_build.

    Returns:
      (recipe_test_api.TestData) TestData for the test.
    """
    cq = kwargs.get('cq')
    # TODO(crbug/1098798): Stop using the recipe properties once they have moved
    # to module properties.
    default_props = {
        '$chromeos/orch_menu': self.get_default_module_properties(cq=cq)
    }
    if not cq:
      default_props['update_manifest_refs'] = default_props[
          '$chromeos/orch_menu']['update_manifest_refs']
    kwargs.setdefault('input_properties', default_props)

    ret = self.m.test_util.test_orchestrator(**kwargs).build
    # Call recipe_test_api.test().
    return super(OrchMenuTestApi, self).test(name, ret, *args)

  def get_default_module_properties(self, cq=False):
    """Return the default properties for the module."""
    ret = dict(stagger_children_seconds=10)
    if not cq:
      ret['update_manifest_refs'] = dict(start='refs/heads/postsubmit')
    return ret
