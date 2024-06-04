# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'exonerate',
    'skylab_results',
]


def RunSteps(api):
  api.exonerate.auto_exoneration_analysis()
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

  _, _ = api.exonerate.exonerate_hwtests(hw_test_failures)
  api.exonerate.auto_exoneration_analysis()
  # To unittest the final return statement.
  api.assertions.assertEqual(
      api.exonerate.get_flake_percent_from_interval_stats([]), (0))
  variant = api.exonerate.get_test_variant_dict('test_name', 'board',
                                                'build_target', 'model')
  api.assertions.assertEqual(variant['variant']['def']['board'], 'board')
  api.assertions.assertEqual(variant['variant']['def']['model'], 'model')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/exonerate':
                  ExonerateProperties(enable_exoneration=True, dry_run=True)
          }))

  yield api.test(
      # v2-enabled just cover the exception scenario: v2 has its own test cases
      'v2-enabled',
      api.buildbucket.try_build(
          experiments=['chromeos.cq.auto.exoneration.v2.enabled']),
      api.properties(
          **{
              '$chromeos/exonerate':
                  ExonerateProperties(enable_exoneration=True, dry_run=True)
          }),
      api.post_process(post_process.DropExpectation))
