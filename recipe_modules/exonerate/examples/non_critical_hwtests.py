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

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exonerate',
    'skylab_results',
]



def RunSteps(api):
  fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
  failing_test_cases = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test2', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='line 22: error'),
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test3', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='blah blah line 4:something went wrong')
  ]
  child_results = [
      ExecuteResponse.TaskResult(name='suite2', state=fail_state,
                                 test_cases=failing_test_cases),
  ]
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(
              test=api.skylab_results.test_api.hw_test(critical=False)),
          status=common_pb2.FAILURE, child_results=child_results)
  ]
  hw_test_failures, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  api.assertions.assertTrue(
      common_pb2.FAILURE in [f.status for f in hw_test_failures])
  api.assertions.assertEqual(exonerated_test_names, [])


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}))
