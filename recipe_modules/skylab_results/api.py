# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
from typing import List
import zlib

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.steps.execution import ExecuteResponses
from PB.test_platform.taskstate import TaskState
from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult, SkylabTask, UnitHwTest


class SkylabResultsApi(recipe_api.RecipeApi):
  """Module for working with Skylab Structs and Hw Test Results."""

  def get_tagged_execute_responses_from_build(self, build):
    try:
      resps = build.output.properties['compressed_responses']
    except ValueError:
      return ExecuteResponses().tagged_responses
    wire_format = zlib.decompress(base64.b64decode(resps))
    responses = ExecuteResponses.FromString(wire_format)
    return responses.tagged_responses

  def translate_result(self, result, task):
    """Translates result to a Skylab result."""
    if result.state.verdict == TaskState.VERDICT_PASSED:
      status = common_pb2.SUCCESS
    elif result.state.life_cycle in (TaskState.LIFE_CYCLE_CANCELLED,
                                     TaskState.LIFE_CYCLE_PENDING,
                                     TaskState.LIFE_CYCLE_ABORTED,
                                     TaskState.LIFE_CYCLE_REJECTED):
      status = common_pb2.INFRA_FAILURE
    else:
      status = common_pb2.FAILURE
    return SkylabResult(task=task, status=status,
                        child_results=result.task_results)

  @staticmethod
  def request_tag(hw_test):
    return hw_test.common.display_name

  def get_previous_results(
      self, task_ids: List[str],
      unit_hw_tests: List[UnitHwTest]) -> List[SkylabResult]:
    """Get the results from the previous tasks with the specified task_ids.

    Args:
      task_ids: The list of Skylab task IDs for which to retrieve results.
      unit_hw_tests: The list of unit_hw_tests for which to retrieve results.

    Returns:
      The list of Skylab results for the specified unit_hw_tests that ran in
      the tasks with the specified task_ids.
    """
    with self.m.step.nest('get previous skylab tasks v2'):
      hw_test_builds = self.m.buildbucket.get_multi(task_ids)
      results = []
      for build in hw_test_builds.values():
        build_url = self.m.buildbucket.build_url(build_id=build.id)
        response = self.get_tagged_execute_responses_from_build(build)
        for uht in unit_hw_tests:
          disp_name = self.request_tag(uht.hw_test)
          if disp_name in response:
            result = response.get(disp_name)
            task = SkylabTask(id=build.id, url=build_url, test=uht.hw_test,
                              unit=uht.unit)
            results.append(self.translate_result(result, task))
      return results

  def extract_failed_test_case_names(
      self, hw_test_results: List[ExecuteResponse.TaskResult],
      ensure_complete: bool = True):
    """Returns the names of the test cases which failed all attempts.

    Args:
      hw_test_results: The results from which to extract the failed tests cases.
      ensure_complete: Only return failed test case names if at least one
        attempt for each shard had terminated uniterrupted. This is to ensure
        the list of failed test cases returned is complete.

    Returns:
      The names of the failed test cases.
    """
    with self.m.step.nest('get failed test cases') as presentation:
      # Group the tasks by shard.
      shard_name_to_task_map = {}
      for result in hw_test_results:
        if result.name not in shard_name_to_task_map:
          shard_name_to_task_map[result.name] = []
        shard_name_to_task_map[result.name].append(result)

      if ensure_complete:
        incomplete_shards = set()
        for shard_name, results in shard_name_to_task_map.items():
          if not any(result.state.life_cycle == TaskState.LIFE_CYCLE_COMPLETED
                     for result in results):
            incomplete_shards.add(shard_name)

          if not any(
              len(result.prejob_steps) > 0 and
              result.prejob_steps[0].verdict == TaskState.VERDICT_PASSED
              for result in results):
            incomplete_shards.add(shard_name)

        if incomplete_shards:
          presentation.step_text = (
              'results may be incomplete, not returning failed test cases')
          presentation.logs['incomplete shards'] = incomplete_shards
          return []

      failed_test_names = set()
      passed_test_names = set()
      for result in hw_test_results:
        for tc in result.test_cases:
          if tc.verdict == TaskState.VERDICT_PASSED:
            passed_test_names.add(tc.name)
          else:
            failed_test_names.add(tc.name)

      # Remove any failed tests which passed in another attempt.
      failed_test_names = failed_test_names.difference(passed_test_names)
      presentation.step_text = 'found %d failed test case(s)' % len(
          failed_test_names)
      presentation.logs['tests'] = list(failed_test_names)
      return list(failed_test_names)

  def extract_failed_test_shard_names(
      self, hw_test_results: List[ExecuteResponse.TaskResult]) -> List[str]:
    """Returns the names of the tests shards which failed all attempts.

    Args:
      hw_test_results: The results from which to extract the failed shard names.

    Returns:
      The names of the failed hw_test_results.
    """
    with self.m.step.nest('get failed test shards') as presentation:
      if not hw_test_results:
        return []

      # Group the tasks by shard.
      shard_name_to_task_map = {}
      for result in hw_test_results:
        if result.name not in shard_name_to_task_map:
          shard_name_to_task_map[result.name] = []
        shard_name_to_task_map[result.name].append(result)

      failed_test_shard_names = []
      for name, results in shard_name_to_task_map.items():
        if not any(result.state.verdict == TaskState.VERDICT_PASSED
                   for result in results):
          failed_test_shard_names.append(name)

      presentation.step_text = 'found %d failed test shard(s)' % len(
          failed_test_shard_names)
      presentation.logs['tests'] = failed_test_shard_names
      return failed_test_shard_names
