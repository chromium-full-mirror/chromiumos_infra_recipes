# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exonerate',
    'skylab_results',
]



def RunSteps(api):
  pass_state = TaskState(verdict=TaskState.VERDICT_PASSED)
  fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
  passing_test_cases = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test1', verdict=TaskState.VERDICT_PASSED),
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test2', verdict=TaskState.VERDICT_PASSED),
  ]
  failing_exonerable_test_case = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test3', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='blah blah line 42:something went wrong'),
  ]
  child_results = [
      ExecuteResponse.TaskResult(name='suite1', state=pass_state,
                                 test_cases=passing_test_cases),
      ExecuteResponse.TaskResult(
          name='suite2', state=fail_state,
          test_cases=(passing_test_cases + failing_exonerable_test_case)),
      ExecuteResponse.TaskResult(name='suite3', state=pass_state,
                                 test_cases=passing_test_cases),
  ]
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE, child_results=child_results),
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.SUCCESS, child_results=child_results[:1]),
  ]
  # Testing the case of disabled exoneration.
  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  api.assertions.assertTrue(
      common_pb2.FAILURE in [f.status for f in hw_test_failures])
  api.assertions.assertEqual(exonerated_test_names, [])

  if not api.exonerate.is_enabled:
    api.assertions.assertEqual(
        api.exonerate.is_hw_result_exonerable(hw_test_failures[0]), False)
    api.exonerate.auto_exoneration_analysis()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(**{
          '$chromeos/exonerate': ExonerateProperties(enable_exoneration=False)
      }), api.post_check(post_process.DoesNotRun, 'exonerate hw tests'))
