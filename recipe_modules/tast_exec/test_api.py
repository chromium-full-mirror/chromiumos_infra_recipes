# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class TastExecTestApi(recipe_test_api.RecipeTestApi):
  """Simulate test data for tast_exec api."""

  @recipe_test_api.mod_test_data
  @staticmethod
  def simulate_test_list_ret(value):
    return value
