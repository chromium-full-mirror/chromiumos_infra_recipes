# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

from google.protobuf import json_format as jsonpb

from PB.testplans.generate_test_plan import GenerateTestPlanRequest
from PB.testplans.generate_test_plan import GenerateTestPlanResponse


class RunPlanApi(recipe_api.RecipeApi):
  """A module for test execution steps"""

  def initialize(self):
    self._test_planner_path = None
    self._test_env_steps = {
        'hw': self.m.skylab.create_suites,
        'vm': self.m.vm_test.run_vm_tests,
        'tast_vm': self.m.vm_test.run_tast_vm_tests,
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

    Returns:
      GenerateTestPlanResponse of test plan.
    """
    self._ensure_test_planner()

    generate_request = GenerateTestPlanRequest()
    generate_request.source_tree_config_path = str(
        self.m.infra_config.get_test_config("source_tree_test_config.cfg"))
    generate_request.target_test_requirements_path = str(
        self.m.infra_config.get_test_config("target_test_requirements.cfg"))
    generate_request.build_report_path.add().file_path = str(build_report_path)

    cmd = [
        self._test_planner_path,
        self.m.json.input(jsonpb.MessageToDict(generate_request)),
    ]
    test_plan_res = self.m.step(name, cmd, stdout=self.m.json.output())

    return jsonpb.ParseDict(test_plan_res.stdout, GenerateTestPlanResponse(),
                            ignore_unknown_fields=True)

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
      for test_unit in test_plan.test_unit:
        test_env, step = self._step(test_unit)
        task = step(test_env, test_unit)
        tasks.append(task)

      # Temporarily flatten list, as other code depends on a flat structure.
      # TODO(yshaul): Remove when other code handle sublists
      return [task for sublist in tasks for task in sublist]

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
    """Returns environment and step function for given test plan step.

    Args:
      * test_unit (TestUnit): Test plan step.

    Returns:
      Tuple(str, callable)
    """
    if not test_unit.WhichOneof('TestCfg'):
      raise self.m.step.StepFailure('No test environment specified.')

    test_env = test_unit.WhichOneof('TestCfg')[:-len('_test_cfg')]
    step = self._test_env_steps.get(test_env, None)
    if step is None:  # pragma: nocover
      raise self.m.step.StepFailure(
          'Unable to execute tests for test environment "%s"' % test_env)

    return test_env, step

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
