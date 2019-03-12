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

  def test_builds(self, name, build_report_path, dep_graph):
    """Shortcut for generate and schedule.

    Args:
      * name (str): The step name.
      * build_report_path (Path): Path to build report.
      * dep_graph (dict): Full dep graph.

    Returns:
      list[swarming.TaskRequestMetadata]

    Raises:
       step.StepFailure
    """
    with self.m.step.nest(name):
      test_plan = self.generate('generate', build_report_path, dep_graph)
      return self.schedule_tests('schedule', test_plan)

  def generate(self, name, build_report_path, dep_graph):
    """Generate test plan.

    Args:
      * name (str): The step name.
      * build_report_path (Path): Path to build report.
      * dep_graph (dict): Full dep graph.
    """
    self._ensure_test_planner()

    # TODO(yshaul): Add real cmd flags / piping when available.
    cmd = [
        self._test_planner_path,
    ]
    test_plan_res = self.m.step(name, cmd, stdout=self.m.json.output())
    return test_plan_res.stdout

  def run_plan(self, name, test_plan):
    """Shortcut for schedule and collect.

    Args:
      * name (str): Step name.
      * test_plan (GenerateTestPlanResponse): Test plan.

    Raises:
       recipe_api.StepFailure
    """
    with self.m.step.nest(name):
      tasks = self.schedule_tests('schedule', test_plan)
      return self.collect_tests('collect', tasks)

  def schedule_tests(self, name, test_plan):
    """Run all test plan steps.
    
    When not running in deferred context, aborts on the first
    scheduling failure.

    Args:
      * name (str): Step name.
      * test_plan (GenerateTestPlanResponse): Test plan.

    Returns:
      list[swarming.TaskRequestMetadata]
    """
    with self.m.step.nest(name):
      tasks = []
      for test_unit in test_plan['test_unit']:
        step = self._step(test_unit)
        task = step(step_name(test_unit), test_unit)
        tasks.append(task)

      return tasks

  def collect_tests(self, name, tasks):
    """Waits for a set of tests to complete, and returns their results.
    Args:
      * name (str): Step name.
      * tasks (list[swarming.TaskResult]): Swarming metadata
          of executing tests.

    Returns:
       list[swarming.TaskResult]
    """
    # TODO(yshaul): Tests are actually scheduled against multiple swarming
    #     servers. Check against them all.
    with self.m.step.nest(name) as result:
      return self.m.swarming.collect('collect tasks', tasks)

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
      return  # pragma: nocover

    with self.m.step.nest('ensure test_planner'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'test_planner')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/test_planner', 'latest')
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
