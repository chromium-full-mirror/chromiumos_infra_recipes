# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import common as rdb_common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exonerate',
    'skylab_results',
]



def RunSteps(api):
  api.assertions.assertTrue(api.exonerate.is_enabled)
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
          human_readable_summary='blah blah line 4:something went wrong'),
      ExecuteResponse.TaskResult.TestCaseResult(
          name='tast.test4', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='blah blah line 42:something went wrong'),
      ExecuteResponse.TaskResult.TestCaseResult(
          name='tast', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='3 failures: test2, test3, tast.test4'),
  ]
  failing_unexonerable_test_cases = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test5', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='meh'),
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test6', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='meh'),
  ]
  failing_incomplete_test_case = [
      ExecuteResponse.TaskResult.TestCaseResult(name='test5')
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
  flaked_child_results = [
      # Flaked.
      # Failed first attempt with unexonerable failure, passed on retry.
      ExecuteResponse.TaskResult(name='critical-flaked-shard-0',
                                 state=pass_state, attempt=0,
                                 test_cases=passing_test_cases),
      ExecuteResponse.TaskResult(name='critical-flaked-shard-0',
                                 state=fail_state, attempt=1,
                                 test_cases=(failing_unexonerable_test_cases)),
  ]
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE, child_results=child_results),
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.SUCCESS, child_results=child_results[:1]),
      # Suite with a mix of flaked and exonerable child results.
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE,
          child_results=flaked_child_results + child_results),
  ]
  # Testing for exoneration fail. (As the result was a success to begin with)
  is_exonerable = api.exonerate.is_hw_result_exonerable(hw_test_failures[1])
  api.assertions.assertEqual(is_exonerable, False)
  # Testing the case of exoneration
  is_exonerable = api.exonerate.is_hw_result_exonerable(hw_test_failures[0])
  api.assertions.assertEqual(is_exonerable, True)

  updated_test_results, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  # Testing the markdown output.
  api.exonerate.populate_exoneration_markdown()
  api.assertions.assertFalse(
      common_pb2.FAILURE in [f.status for f in updated_test_results])
  api.assertions.assertEqual(exonerated_test_names,
                             ['target.hw.bvt-cq', 'target.hw.bvt-cq'])
  api.assertions.assertEqual(len(updated_test_results[0].child_results), 3)

  # Testing the case where test doesn't get exonerated.
  child_results = [
      ExecuteResponse.TaskResult(name='suite1', state=pass_state,
                                 test_cases=passing_test_cases),
      ExecuteResponse.TaskResult(
          name='suite2', state=fail_state,
          test_cases=(passing_test_cases + failing_unexonerable_test_cases))
  ]
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE, child_results=child_results),
  ]
  is_exonerable = api.exonerate.is_hw_result_exonerable(hw_test_failures[0])
  api.assertions.assertEqual(is_exonerable, False)
  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  api.assertions.assertTrue(
      common_pb2.FAILURE in [f.status for f in hw_test_failures])
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(len(hw_test_failures[0].child_results), 2)

  # Testing the case of empty child_results and empty test_cases.
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE, child_results=[])
  ]

  is_exonerable = api.exonerate.is_hw_result_exonerable(hw_test_failures[0])
  api.assertions.assertEqual(is_exonerable, False)

  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(len(hw_test_failures[0].child_results), 0)

  child_results_with_empty_test_cases = [
      ExecuteResponse.TaskResult(name='suite1', state=fail_state, test_cases=[])
  ]
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE,
          child_results=child_results_with_empty_test_cases)
  ]
  is_exonerable = api.exonerate.is_hw_result_exonerable(hw_test_failures[0])
  api.assertions.assertEqual(is_exonerable, False)

  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(len(hw_test_failures[0].child_results), 1)

  child_results_with_incomplete_test_cases = [
      ExecuteResponse.TaskResult(name='suite1', state=fail_state,
                                 test_cases=failing_incomplete_test_case)
  ]
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE,
          child_results=child_results_with_incomplete_test_cases)
  ]
  is_exonerable = api.exonerate.is_hw_result_exonerable(hw_test_failures[0])
  api.assertions.assertEqual(is_exonerable, False)

  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(len(hw_test_failures[0].child_results), 1)

  api.exonerate.print_stats(property_name='exoneration_stats')
  api.exonerate.auto_exoneration_analysis()
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
      api.exonerate.is_exonerated(
          test_result_pb2.TestResult(test_id='tast.test4', variant=variant)),
      True)

  # Testing the case of provision failures.
  child_results = [
      ExecuteResponse.TaskResult(name='suite1', state=pass_state,
                                 test_cases=passing_test_cases),
      ExecuteResponse.TaskResult(
          name='suite2', state=fail_state,
          test_cases=failing_exonerable_test_cases, prejob_steps=[
              ExecuteResponse.TaskResult.TestCaseResult(
                  name='provision', verdict=TaskState.VERDICT_FAILED)
          ])
  ]
  hw_test_failure = api.skylab_results.test_api.skylab_result(
      task=api.skylab_results.test_api.skylab_task(), status=common_pb2.FAILURE,
      child_results=child_results)

  # Do not exonerate by default.
  is_exonerable = api.exonerate.is_hw_result_exonerable(hw_test_failure)
  api.assertions.assertFalse(is_exonerable)

  # Exonerate when exonerate_prejob_failures is True.
  is_exonerable = api.exonerate.is_hw_result_exonerable(
      hw_test_failure, exonerate_prejob_failures=True)
  api.assertions.assertTrue(is_exonerable)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}))
