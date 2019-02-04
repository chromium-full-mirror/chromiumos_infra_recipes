# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

class RunPlanApi(recipe_api.RecipeApi):
  """A module for test execution steps"""

  def initialize(self):
    self._test_env_steps = {
      'hw': self.m.skylab.create_suite
    }

  def run(self, name, test_plan):
    """Run all test plan steps. Aborts on the first step failure.

    Args:
      * name (str): Step name.
      * test_plan (GenerateTestPlanResponse): Test plan.
    """
    with self.m.step.nest(name):
      for test_unit in test_plan['test_plan']:
        step = self._step(test_unit)
        step(step_name(test_unit), test_unit)

  def _step(self, test_unit):
    """Returns step function for given test plan step.

    Args:
      * test_unit (TestUnit): Test plan step.

    Returns:
      callable
    """
    test_env = test_unit['test_env']
    step = self._test_env_steps.get(test_env, None)
    if step is None:
      raise self.m.step.StepFailure('Unknown test environment "%s"' % test_env)

    return step

def step_name(test_plan):
  """Returns step name for test plan.

  Args:
    * test_plan (TestPlan): Test plan step.

  Returns:
    str: Step name
  """
  return 'execute %(test_env)s suite %(test_suite)s' % test_plan
