# -*- coding: utf-8 -*-

# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exonerate',
    'skylab',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import common as rdb_common_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.exonerate.fetch_config(api.exonerate.test_api.empty_config_file_contents)
  pass_state = TaskState(verdict=TaskState.VERDICT_PASSED)
  fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
  passing_test_cases = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test1', verdict=TaskState.VERDICT_PASSED),
  ]
  failing_exonerable_test_cases = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test2', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='line 22: error'),
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test3', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='blah blah line 42:something went wrong'),
      ExecuteResponse.TaskResult.TestCaseResult(
          name='tast', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='2 failures: test2, test3'),
  ]
  failing_unexonerable_test_case = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test4', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='meh'),
  ]
  child_results = [
      ExecuteResponse.TaskResult(name='suite1', state=pass_state,
                                 test_cases=passing_test_cases),
      ExecuteResponse.TaskResult(
          name='suite2', state=fail_state,
          test_cases=(passing_test_cases + failing_exonerable_test_cases)),
      ExecuteResponse.TaskResult(name='suite3', state=pass_state,
                                 test_cases=passing_test_cases),
  ]
  hw_test_failures = [
      api.skylab.test_api.skylab_result(task=api.skylab.test_api.skylab_task(),
                                        status=common_pb2.FAILURE,
                                        child_results=child_results),
      api.skylab.test_api.skylab_result(task=api.skylab.test_api.skylab_task(),
                                        status=common_pb2.SUCCESS,
                                        child_results=child_results[:1]),
  ]
  # Testing the case of exoneration
  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  # Testing the markdown output.
  md_string = api.exonerate.get_exoneration_markdown()
  api.assertions.assertTrue('bvt-cq' in md_string)
  api.assertions.assertFalse(
      common_pb2.FAILURE in [f.status for f in hw_test_failures])
  api.assertions.assertEqual(exonerated_test_names, ['target.hw.bvt-cq'])
  api.assertions.assertEqual(len(hw_test_failures[0].child_results), 3)

  child_results = [
      ExecuteResponse.TaskResult(name='suite1', state=pass_state,
                                 test_cases=passing_test_cases),
      ExecuteResponse.TaskResult(
          name='suite2', state=fail_state,
          test_cases=(passing_test_cases + failing_unexonerable_test_case))
  ]
  hw_test_failures = [
      api.skylab.test_api.skylab_result(task=api.skylab.test_api.skylab_task(),
                                        status=common_pb2.FAILURE,
                                        child_results=child_results),
  ]
  # Testing the case where test doesn't get exonerated
  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  api.assertions.assertTrue(
      common_pb2.FAILURE in [f.status for f in hw_test_failures])
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(len(hw_test_failures[0].child_results), 2)

  # Testing the case of empty child_results and empty test_cases.
  hw_test_failures = [
      api.skylab.test_api.skylab_result(task=api.skylab.test_api.skylab_task(),
                                        status=common_pb2.FAILURE,
                                        child_results=[])
  ]
  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(len(hw_test_failures[0].child_results), 0)

  child_results_with_empty_test_cases = [
      ExecuteResponse.TaskResult(name='suite1', state=fail_state, test_cases=[])
  ]
  hw_test_failures = [
      api.skylab.test_api.skylab_result(
          task=api.skylab.test_api.skylab_task(), status=common_pb2.FAILURE,
          child_results=child_results_with_empty_test_cases)
  ]
  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(len(hw_test_failures[0].child_results), 1)

  api.exonerate.print_stats()
  variant = rdb_common_pb2.Variant()
  getattr(variant, 'def')['build_target'] = 'build_target_name'
  api.assertions.assertEqual(
      api.exonerate.is_exonerated(
          test_result_pb2.TestResult(test_id='test2', variant=variant)), True)
  bad_variant = rdb_common_pb2.Variant()
  getattr(bad_variant, 'def')['build_target'] = 'bad_build_target'
  api.assertions.assertEqual(
      api.exonerate.is_exonerated(
          test_result_pb2.TestResult(test_id='test2', variant=bad_variant)),
      False)
  api.assertions.assertEqual(
      api.exonerate.is_exonerated(
          test_result_pb2.TestResult(test_id='badtest', variant=variant)),
      False)
  api.assertions.assertEqual(
      api.exonerate.is_exonerated(
          test_result_pb2.TestResult(test_id='test1', variant=variant)), False)
  api.assertions.assertEqual(
      api.exonerate.get_tastless_name('tast.test_name'), 'test_name')
  api.assertions.assertEqual(
      api.exonerate.get_tastless_name('test_name'), 'test_name')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}))
