# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'skylab_results',
]



def RunSteps(api):
  child_results_json = api.properties.get('child_results', [])
  child_results = [
      json_format.Parse(result, ExecuteResponse.TaskResult())
      for result in child_results_json
  ]
  ensure_complete = api.properties.get('ensure_complete', True)
  failed_test_names = api.skylab_results.extract_failed_test_case_names(
      child_results, ensure_complete)
  api.assertions.assertCountEqual(
      failed_test_names, api.properties.get('expected_failed_test_names', []))


def GenTests(api):

  def task_result(task_result_name='task-1', failed_test_names=None,
                  passed_test_names=None,
                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED,
                  provision_verdict=TaskState.VERDICT_PASSED):
    tr = ExecuteResponse.TaskResult()
    tr.state.life_cycle = life_cycle
    tr.name = task_result_name
    if provision_verdict is not None:
      provision = tr.prejob_steps.add()
      provision.name = 'provision'
      provision.verdict = provision_verdict
    for test_name in passed_test_names or []:
      test_case = tr.test_cases.add()
      test_case.name = test_name
      test_case.verdict = TaskState.VERDICT_PASSED
    for test_name in failed_test_names or []:
      test_case = tr.test_cases.add()
      test_case.name = test_name
      test_case.verdict = TaskState.VERDICT_FAILED
    return json_format.MessageToJson(tr)

  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )

  child_results = [
      task_result(failed_test_names=['test1'],
                  life_cycle=TaskState.LIFE_CYCLE_ABORTED),
      task_result(failed_test_names=['test2'],
                  life_cycle=TaskState.LIFE_CYCLE_CANCELLED),
      task_result(failed_test_names=['test3'],
                  life_cycle=TaskState.LIFE_CYCLE_REJECTED),
  ]
  yield api.test(
      'not-lifecycle-complete',
      api.properties(child_results=child_results),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-lifecycle-complete-ensure-complete-false',
      api.properties(child_results=child_results, ensure_complete=False,
                     expected_failed_test_names=['test1', 'test2', 'test3']),
      api.post_process(post_process.DropExpectation),
  )

  child_results = [
      task_result(failed_test_names=['test1'],
                  life_cycle=TaskState.LIFE_CYCLE_ABORTED),
      task_result(failed_test_names=['test2', 'test3'],
                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
      task_result(passed_test_names=['test4'],
                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
  ]
  yield api.test(
      'agg-failed-tests-across-multiple-runs',
      api.properties(child_results=child_results,
                     expected_failed_test_names=['test1', 'test2', 'test3']),
      api.post_process(post_process.DropExpectation),
  )

  child_results = [
      task_result(passed_test_names=['test1'], failed_test_names=['test3'],
                  life_cycle=TaskState.LIFE_CYCLE_ABORTED),
      task_result(passed_test_names=['test3'],
                  failed_test_names=['test1', 'test2'],
                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
  ]
  yield api.test(
      'failed-test-passed-in-other-attempt',
      api.properties(child_results=child_results,
                     expected_failed_test_names=['test2']),
      api.post_process(post_process.DropExpectation),
  )

  child_results = [
      task_result(task_result_name='task-1', failed_test_names=['test3'],
                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED,
                  provision_verdict=None),
      task_result(task_result_name='task-2',
                  failed_test_names=['test1', 'test2'],
                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
  ]
  yield api.test(
      'missing-prejob-result',
      api.properties(child_results=child_results),
      api.post_process(post_process.DropExpectation),
  )

  child_results = [
      task_result(task_result_name='task-1', failed_test_names=['test3'],
                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED,
                  provision_verdict=TaskState.VERDICT_FAILED),
      task_result(task_result_name='task-2',
                  failed_test_names=['test1', 'test2'],
                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
  ]
  yield api.test(
      'failed-prejob',
      api.properties(child_results=child_results),
      api.post_process(post_process.DropExpectation),
  )
