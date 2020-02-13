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
  task_result = api.tast_results.get_results(temp_dir, 'fancy-suite')
  api.tast_results.print_results(task_result, temp_dir)

  failures = api.tast_results.get_failures(task_result)
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
  api.tast_results.print_results(passed_task_result, temp_dir)
  fishy_task_result = ExecuteResponse.TaskResult(name=task_result.name,
                                                 state=task_result.state)
  api.tast_results.print_results(fishy_task_result, temp_dir)


def GenTests(api):
  yield api.test('basic')
