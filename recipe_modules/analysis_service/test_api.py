# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test functions for the Analysis Service API."""

from recipe_engine import recipe_test_api


class AnalysisServiceApi(recipe_test_api.RecipeTestApi):

  @recipe_test_api.mod_test_data
  @staticmethod
  def optional_field_name(field_name):
    """Returns the full name of the field to be marked as optional for logging."""
    return field_name
