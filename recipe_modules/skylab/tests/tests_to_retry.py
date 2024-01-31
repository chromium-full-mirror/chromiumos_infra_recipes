# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'skylab',
]



def RunSteps(api):
  execute_response_json = api.properties.get('execute_response')
  execute_response = json_format.Parse(execute_response_json, ExecuteResponse())

  actual = api.skylab._tests_to_retry(
      execute_response, api.properties.get('tast_first_class', False))
  expected = api.properties.get('expected_tests_to_retry', [])
  api.assertions.assertCountEqual(actual, expected)


def GenTests(api):

  execute_response_json = json_format.MessageToJson(ExecuteResponse())
  yield api.test(
      'empty',
      api.properties(expected_tests_to_retry=[],
                     execute_response=execute_response_json),
      api.post_process(post_process.DropExpectation),
  )

  execute_response = ExecuteResponse()
  tr = execute_response.task_results.add()
  tr.name = 'tauto.something-something'
  tr.state.life_cycle = TaskState.LIFE_CYCLE_COMPLETED
  prejob = tr.prejob_steps.add()
  prejob.name = 'provision'
  prejob.verdict = TaskState.VERDICT_PASSED
  test_case = tr.test_cases.add()
  test_case.name = 'tast.something-something'
  test_case.verdict = TaskState.VERDICT_FAILED
  execute_response_json = json_format.MessageToJson(execute_response)

  yield api.test(
      'tast-first-class',
      api.properties(expected_tests_to_retry=['tast.something-something'],
                     execute_response=execute_response_json,
                     tast_first_class=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-tast-first-class',
      api.properties(
          expected_tests_to_retry=['tauto.something-something'],
          execute_response=execute_response_json,
      ),
      api.post_process(post_process.DropExpectation),
  )
