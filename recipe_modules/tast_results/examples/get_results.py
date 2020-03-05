# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'tast_results',
]

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState


def RunSteps(api):
  temp_dir = api.path.mkdtemp(prefix='test-results')
  task_result = api.tast_results.get_results(temp_dir, 'fancy-suite', '1')
  failures = api.tast_results.get_failures(task_result)
  api.tast_results.print_results(failures, False)
  # fake test case code.
  api.tast_results.fake_empty_result_test_cases()

  # tests_to_retry unittesting.
  tests, _ = api.tast_results.get_tests_to_retry(task_result)
  api.assertions.assertEqual(len(tests), 1)
  empty_task_result = ExecuteResponse.TaskResult(
      name=task_result.name,
      state=TaskState(verdict=TaskState.VERDICT_UNSPECIFIED))
  api.tast_results.get_tests_to_retry(empty_task_result)

  api.assertions.assertEqual(len(failures), 1)
  api.assertions.assertEqual(failures[0].kind, 'vm test')
  api.assertions.assertEqual(failures[0].fatal, True)
  api.assertions.assertEqual(failures[0].title, 'arc.Boot')

  passed_task_result = ExecuteResponse.TaskResult(
      name=task_result.name, state=TaskState(verdict=TaskState.VERDICT_PASSED),
      test_cases=[
          x for x in task_result.test_cases
          if x.verdict == TaskState.VERDICT_PASSED
      ])
  failures = api.tast_results.get_failures(passed_task_result)
  api.tast_results.print_results(failures, False)
  tests, _ = api.tast_results.get_tests_to_retry(passed_task_result)
  api.assertions.assertEqual(tests, [])
  fishy_task_result = ExecuteResponse.TaskResult(name=task_result.name,
                                                 state=task_result.state)
  failures = api.tast_results.get_failures(fishy_task_result)
  api.tast_results.print_results(failures, True)


def GenTests(api):
  yield api.test('basic')
