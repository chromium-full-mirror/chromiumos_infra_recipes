# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing Chrome OS recipes.

This module provides helpers to make testing Chrome OS recipes simpler and more
consistent.
"""

import os
from recipe_engine import recipe_test_api


def _read_test_file(filename):
  """Read the content of a file in this directory.

  Args:
    filename (str): The basename of the file (located in this directory) to
        read.

  Returns:
    (str): The contents of the file.
  """
  with open(os.path.join(os.path.abspath(os.path.dirname(__file__)),
                         filename)) as f:
    return f.read().strip()


class PaygenTestApi(recipe_test_api.RecipeTestApi):
  """Helper class for testing Chrome OS Paygen Recipes."""

  EXAMPLE_PAYGEN_JSON = _read_test_file('test_paygen.json')
  EXAMPLE_EMPTY_JSON = "{}"
  EXAMPLE_NOT_EVEN_JSON = "dawiojdoiawjdioawjdow"
  ALL_EXAMPLE_JSONS = [
      EXAMPLE_PAYGEN_JSON, EXAMPLE_EMPTY_JSON, EXAMPLE_NOT_EVEN_JSON
  ]

  def test_paygen(self, step_name, json_return):
    """Mock up step results for the GS cat."""
    test_response = self.m.step.step_data(
        step_name, stdout=self.m.raw_io.output(json_return))
    return test_response
