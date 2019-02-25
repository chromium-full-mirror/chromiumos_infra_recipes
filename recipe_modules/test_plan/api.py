# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

class RunPlanApi(recipe_api.RecipeApi):
  """A module for test execution steps"""

  def initialize(self):
    self._test_planner_path = None
    self._test_env_steps = {
      'hw': self.m.skylab.create_suite,
      'vm': self.m.vm_test.run_vm_test,
      'tast_vm': self.m.vm_test.run_tast_test,
    }

  def generate(self, name, build_report, dep_graph):
    """Generate test plan.

    Args:
      * name (str): The step name.
      * build_report (dict): Full build report.
      * dep_graph (dict): Full dep graph.
    """
    self._ensure_test_planner()

    # TODO(yshaul): Add real cmd flags / piping when available.
    cmd = [
      self._test_planner_path,
    ]
    try:
      self.m.step(name, cmd, stdout=self.m.json.output())
    finally:
      result = self.m.step.active_result
      return result.stdout

  def run(self, name, test_plan):
    """Run all test plan steps. Aborts on the first step failure.

    Args:
      * name (str): Step name.
      * test_plan (GenerateTestPlanResponse): Test plan.
    """
    with self.m.step.nest(name) as result:
      tasks = []
      for test_unit in test_plan['test_plan']:
        step = self._step(test_unit)
        task = step(step_name(test_unit), test_unit)
        tasks.append(task)

      swarming_results = self.m.swarming.collect('collect test results', tasks)

      success = True
      for idx, swarming_result in enumerate(swarming_results):
        # We don't have a great way of highlighting failed tests.
        # Group failed tests together by prepending status.
        log_name = 'SUCCESS - ' if swarming_result.success else 'FAILURE - '
        if isinstance(tasks[idx], str):
          log_name += tasks[idx]
        else:
          log_name += tasks[idx].name

        # Until parallel recipes materializes, dump output to step log
        result.presentation.logs[log_name] = [
            swarming_result.output
        ]

        if swarming_result.success:
          result.presentation.status = 'SUCCESS'
        else:
          result.presentation.status = 'FAILURE'

        success &= swarming_result.success

      if not success:
        raise self.m.step.StepFailure('Failed one or more tests')

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

  def _ensure_test_planner(self):
    """Ensure the test_planner cli is installed."""
    if self._test_planner_path:
      return # pragma: nocover

    with self.m.step.nest('ensure test_planner'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'test_planner')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/test_planner',
                         'latest')
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._test_planner_path = cipd_dir.join('test_planner')


def step_name(test_plan):
  """Returns step name for test plan.

  Args:
    * test_plan (TestPlan): Test plan step.

  Returns:
    str: Step name
  """
  return 'execute %(test_env)s suite %(test_suite)s' % test_plan
