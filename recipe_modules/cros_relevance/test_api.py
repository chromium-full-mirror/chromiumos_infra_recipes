# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.generate_build_plan import GenerateBuildPlanResponse


class CrosRelevanceTestApi(recipe_test_api.RecipeTestApi):
  """Generates test data for CrosRelevanceApi."""

  def simulated_get_necessary_builders(self, necessary_builders):
    """Simulates a call to get_necessary_builders.

    Args:
      necessary_builders(list[str]): List of builder names to return.

    Returns:
      StepData: Resulting step data.
    """
    builds_to_run = [BuilderConfig.Id(name=b) for b in necessary_builders]
    resp = GenerateBuildPlanResponse(builds_to_run=builds_to_run)
    return self.step_data('plan builds.read output file',
                          self.m.file.read_raw(resp.SerializeToString()))
