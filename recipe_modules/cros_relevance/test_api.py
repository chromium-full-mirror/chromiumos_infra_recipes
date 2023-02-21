# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.generate_build_plan import GenerateBuildPlanResponse
from recipe_engine import recipe_test_api


class CrosRelevanceTestApi(recipe_test_api.RecipeTestApi):
  """Generates test data for CrosRelevanceApi."""

  def simulated_run_build_planner(self, necessary_builders, skipped_builders):
    """Simulates a call to get_necessary_builders.

    Args:
      necessary_builders(list[str]): List of builder names to return.
      skipped_builders(list[str]): List of skipped builder names to return.

    Returns:
      StepData: Resulting step data.
    """
    builds_to_run = [BuilderConfig.Id(name=b) for b in necessary_builders]
    builds_to_skip = [BuilderConfig.Id(name=b) for b in skipped_builders]
    resp = GenerateBuildPlanResponse(builds_to_run=builds_to_run,
                                     skip_for_run_when_rules=builds_to_skip)
    return self.step_data(
        "plan builds.read output file",
        self.m.file.read_raw(resp.SerializeToString()),
    )

  @recipe_test_api.mod_test_data
  @staticmethod
  def toolchain_cls_applied(value):
    """Return value for toolchain_cls_applied when testing."""
    return value
