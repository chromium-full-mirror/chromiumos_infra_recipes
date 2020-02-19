# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class SwarmingCliTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the swarming CLI module."""

  def swarming_bot_step_test_data(self):
    step_data = ('chromeos-ci-cq-us-central1-b-x1-0-igx0\n' +
                 'chromeos-ci-cq-us-central1-b-x1-4-gaf9\n')
    return step_data
