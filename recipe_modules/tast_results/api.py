# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format as jsonpb
from recipe_engine import recipe_api

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState
from PB.tast.test_result import TestResult

import json
import ntpath


class TastResultsApi(recipe_api.RecipeApi):
  """A module to process tast-results/ directory."""

  def get_results(self, test_results_path):
    """Return the test results decoded from the results.json.

    Args:
      test_results_path (Path): Path to test_results/.

    Returns:
      A consolidated Data Structure summarizing all results from a run.
      Currently this is an ExecuteResponse.
      https://crrev.com/ee30a869473a8ee54246e0469ede2aa010fb2e48/src/test_platform/steps/execution.proto#44
    """
    with self.m.step.nest('process tast output'):
      test_results = self._read_results_json(test_results_path)
      consolidated_result = ExecuteResponse.ConsolidatedResult(
          attempts=[self.convert_to_taskresult(r) for r in test_results])

      # If even one test failed, the suite should report failure.
      all_verdicts = [a.state.verdict for a in consolidated_result.attempts]
      overall_state = TaskState(verdict=TaskState.VERDICT_PASSED,
                                life_cycle=TaskState.LIFE_CYCLE_COMPLETED)
      if TaskState.VERDICT_FAILED in all_verdicts:
        overall_state.verdict = TaskState.VERDICT_FAILED
      return ExecuteResponse(consolidated_results=[consolidated_result],
                             state=overall_state)

  def _read_results_json(self, test_results_path):
    """Read the results.json file and return structured contents.

    Args:
      test_results_path (Path): Path to test_results/.

    Returns:
      list(TestResult).
      https://crrev.com/62d6530f6f61417cf47a2bcea8bb714470ef5ca2/src/tast/test_result.proto
    """
    list_of_results = self.m.file.read_json(
        'read results.json', test_results_path.join('results.json'),
        test_data=self.test_api.test_results_json)
    return [
        jsonpb.ParseDict(result, TestResult()) for result in list_of_results
    ]

  def convert_to_taskresult(self, test_result):
    """Convert Tast's result into CTP format.

    Args:
      test_result (TestResult): TestResult to be converted.

    Returns:
      TaskResult with the same info.
    """
    task_result = ExecuteResponse.TaskResult()
    task_result.name = test_result.name
    task_result.attempt = 0

    task_summary = ""
    task_result.state.life_cycle = TaskState.LIFE_CYCLE_COMPLETED
    if test_result.skip_reason:
      task_result.state.verdict = TaskState.VERDICT_NO_VERDICT
      task_summary = test_result.skip_reason
    elif not test_result.errors:
      task_result.state.verdict = TaskState.VERDICT_PASSED
    else:
      task_result.state.verdict = TaskState.VERDICT_FAILED
      task_summary = ', '.join([e.reason for e in test_result.errors])

    task_result.test_cases.extend([
        ExecuteResponse.TaskResult.TestCaseResult(
            name=task_result.name,
            verdict=task_result.state.verdict,
            human_readable_summary=task_summary,
        )
    ])
    return task_result

  def print_results(self, execute_response, test_results_path):
    """Print results for the user.

    Args:
      execute_response(ExecuteResponse): result of the run.
      test_results_path (Path): Path to test_results/.
    """
    for task_result in execute_response.consolidated_results[0].attempts:
      if task_result.state.verdict == TaskState.VERDICT_FAILED:
        with self.m.step.nest(task_result.name) as step:
          step.presentation.step_text = (
              task_result.test_cases[0].human_readable_summary)
          step.presentation.status = self.m.step.FAILURE

          # Making a separate step so as to not show these to user.
          # This step should always be collapsed for end user.
          with self.m.step.nest('housekeeping'):
            test_log_dir = test_results_path.join('tests').join(
                task_result.name)
            for file in self.m.file.listdir('ls', test_log_dir,
                                            test_data=['dummy_file']):
              filename = ntpath.basename(str(file))
              step.presentation.logs[filename] = self.m.file.read_text(
                  'reading file', file)
