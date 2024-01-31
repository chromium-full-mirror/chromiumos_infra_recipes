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
  api.exonerate.fetch_config(api.exonerate.test_api.empty_config_file_contents)
  fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
  # Test cases are empty if they are skipped because of provision failure.
  provision_test_cases = [
      ExecuteResponse.TaskResult.TestCaseResult(name='test2'),
      ExecuteResponse.TaskResult.TestCaseResult(name='test3'),
      ExecuteResponse.TaskResult.TestCaseResult(name='tast.test4'),
  ]
  # Prejob step has a failure verdict.
  prejob_steps = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='provision', verdict=TaskState.VERDICT_FAILED),
  ]
  child_results = [
      ExecuteResponse.TaskResult(name='suite1', state=fail_state,
                                 test_cases=provision_test_cases,
                                 prejob_steps=prejob_steps)
  ]
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE, child_results=child_results),
  ]

  updated_test_results, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  # Check that no exoneration occurred.
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(updated_test_results[0].status, common_pb2.FAILURE)


  crash_test_cases = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test2', verdict=TaskState.VERDICT_NO_VERDICT),
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test3', verdict=TaskState.VERDICT_NO_VERDICT),
  ]
  child_results = [
      ExecuteResponse.TaskResult(name='suite1', state=fail_state,
                                 test_cases=crash_test_cases)
  ]
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE, child_results=child_results),
  ]

  updated_test_results, exonerated_test_names = api.exonerate.exonerate_hwtests(
      hw_test_failures)
  # Check that no exoneration occurred.
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(updated_test_results[0].status, common_pb2.FAILURE)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}))
