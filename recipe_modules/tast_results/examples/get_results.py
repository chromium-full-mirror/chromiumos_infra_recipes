# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'tast_results',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  temp_dir = api.path.mkdtemp(prefix='test-results')
  task_result = api.tast_results.get_results(temp_dir, 'fancy-suite', '1',
                                             ['arc.Boot'])
  failures, test_cases = api.tast_results.get_failures(task_result)
  api.tast_results.print_results(failures, False)
  api.assertions.assertEqual(test_cases[0]['name'], 'arc.Boot')
  # fake test case code.

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
  task_result = api.tast_results.get_results(
      temp_dir, 'fancy-suite', '1',
      ['arc.Boot', 'arc.StartStop', 'some.Test', 'some.OtherTest'])
  failures, test_cases = api.tast_results.get_failures(task_result)
  api.assertions.assertEqual(len(failures), 4)
  api.assertions.assertEqual(failures[0].kind, 'vm test')
  api.assertions.assertEqual(failures[0].fatal, True)
  api.assertions.assertEqual(failures[0].title, 'arc.Boot')
  api.assertions.assertEqual(test_cases[1]['name'], 'arc.StartStop')
  api.assertions.assertEqual(test_cases[1]['humanReadableSummary'],
                             u'Test did not run')

  passed_task_result = ExecuteResponse.TaskResult(
      name=task_result.name, state=TaskState(verdict=TaskState.VERDICT_PASSED),
      test_cases=[
          x for x in task_result.test_cases
          if x.verdict == TaskState.VERDICT_PASSED
      ])
  failures, test_cases = api.tast_results.get_failures(passed_task_result)
  api.assertions.assertEqual(test_cases, [])
  api.tast_results.print_results(failures, False)
  tests, _ = api.tast_results.get_tests_to_retry(passed_task_result)
  api.assertions.assertEqual(tests, [])
  fishy_task_result = ExecuteResponse.TaskResult(name=task_result.name,
                                                 state=task_result.state)
  failures, test_cases = api.tast_results.get_failures(fishy_task_result)
  api.assertions.assertEqual(test_cases, [])
  api.tast_results.print_results(failures, True)


def GenTests(api):
  build = api.buildbucket.ci_build_message()
  build.input.properties['buildTarget'] = {'name': 'amd64-generic'}
  yield api.test('basic', api.buildbucket.build(build))

  yield api.test('resultdb-not-enabled')

  build.critical = common_pb2.NO
  yield api.test('non-critical', api.buildbucket.build(build))
