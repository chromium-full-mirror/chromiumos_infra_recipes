# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CrosTestProctorTestApi(recipe_test_api.RecipeTestApi):
  """Test data for cros_test_proctor api."""

  @recipe_test_api.mod_test_data
  @staticmethod
  def builders_tested_in_this_run(builders):
    return builders
