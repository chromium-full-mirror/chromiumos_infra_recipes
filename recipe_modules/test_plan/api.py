# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple
from itertools import chain
from itertools import groupby
from urlparse import urlparse

from recipe_engine import recipe_api

from google.protobuf import json_format as jsonpb

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.testplans.generate_test_plan import GenerateTestPlanRequest
from PB.testplans.generate_test_plan import GenerateTestPlanResponse


ScheduleResult = namedtuple('ScheduleResult', ['swarming_server', 'tasks'])


class RunPlanApi(recipe_api.RecipeApi):
  """A module for test execution steps"""

  def initialize(self):
    self._test_planner_path = None
    self._test_env_steps = {
        'hw': self.m.skylab.create_suites,
        'vm': self.m.vm_test.run_vm_tests,
        'tast_vm': self.m.vm_test.run_tast_vm_tests,
    }

  def test_builds(self, name, builds):
    """Shortcut for generate and schedule.

    Args:
      * name (str): The step name.
      * builds (list[build_pb2.Build]): builds to test.

    Returns:
      list[swarming.TaskRequestMetadata]

    Raises:
       step.StepFailure
    """
    with self.m.step.nest(name):
      test_plan = self.generate('generate', builds)
      return self.schedule_tests('schedule', test_plan)

  def generate(self, name, builds):
    """Generate test plan.

    Args:
      * name (str): The step name.
      * builds (list[build_pb2.Build]): builds to test.

    Returns:
      GenerateTestPlanResponse of test plan.
    """
    self._ensure_test_planner()

    generate_request = GenerateTestPlanRequest()
    generate_request.chromiumos_checkout_root = str(
        self.m.cros_source.master_path)
    generate_request.repo_tool_path = str(self.m.repo.repo_path)
    for build in builds:
      generate_request.buildbucket_protos.add().serialized_proto = (
        build_pb2.Build.SerializeToString(build))

    cmd = [
        self._test_planner_path,
        'gen-test-plan',
        '--input_json',
        self.m.json.input(jsonpb.MessageToDict(generate_request)),
        '--output_json',
        self.m.json.output(),
    ]
    test_plan_res = self.m.step(name, cmd)
    output = test_plan_res.json.output
    return jsonpb.ParseDict(output, GenerateTestPlanResponse(),
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
      list[ScheduleResult]
    """
    results = []
    with self.m.step.defer_results():
      with self.m.step.nest(name):
        for build_target, test_units in groupby(
            test_plan.test_unit,
            lambda unit: unit.scheduling_requirements.build_target):
          with self.m.step.nest(build_target):
            for test_unit in test_units:
              if not test_unit.WhichOneof('TestCfg'):
                raise self.m.step.StepFailure('No test environment specified.')
              test_env = test_unit.WhichOneof('TestCfg')[:-len('_test_cfg')]
              # TODO(https://crbug.com/953961): Remove references to GCE tests.
              if test_env == 'gce':
                continue
              # We don't support Moblab VM tests yet.
              # TODO(https://crbug.com/954276): Figure out how to support them.
              if test_env == 'moblab_vm':
                continue
              step = self._test_env_steps.get(test_env)
              if step is None:  # pragma: nocover
                raise self.m.step.StepFailure(
                    'Unable to execute tests for test environment "%s"' % test_env)
              results.append(step(test_env, test_unit))

    successful_results = []
    for r in results:
      if r.is_ok:
        successful_results.append(r.get_result())
    return successful_results

  def collect_tests(self, name, schedule_results):
    """Waits for a set of tests to complete, and returns their results.
    Args:
      * name (str): Step name.
      * schedule_results (list[ScheduleResult]): List of ScheduleResult from
          call to schedule.

    Returns:
       list[swarming.TaskResult]
    """
    results = []
    with self.m.step.nest(name) as result:
      swarming_servers = set(
          [result.swarming_server for result in schedule_results])
      for swarming_server in swarming_servers:
        # pluck task ids rather than passing in tasks directly.
        # This is because skylab.create_suites ducks TaskRequestMetadata,
        # and collect asserts type of TaskRequestMetadata.
        tasks = chain.from_iterable([
            result.tasks
            for result in schedule_results
            if result.swarming_server == swarming_server
        ])
        task_ids = [str(task.id) for task in tasks]

        with self.m.swarming.with_server(swarming_server):
          hostname = urlparse(swarming_server).hostname
          results += self.m.swarming.collect('%s' % hostname, task_ids)

    return results

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

        self._test_planner_path = cipd_dir.join('test_plan_generator')
