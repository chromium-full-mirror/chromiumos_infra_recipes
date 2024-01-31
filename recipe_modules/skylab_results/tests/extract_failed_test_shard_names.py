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
  failed_test_names = api.skylab_results.extract_failed_test_shard_names(
      child_results)
  api.assertions.assertCountEqual(
      failed_test_names, api.properties.get('expected_failed_test_names', []))


def GenTests(api):

  def task_result(shard_name, verdict=TaskState.VERDICT_UNSPECIFIED):
    tr = ExecuteResponse.TaskResult()
    tr.name = shard_name
    tr.state.verdict = verdict
    return json_format.MessageToJson(tr)

  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )

  child_results = [
      task_result('shard1', TaskState.VERDICT_FAILED),
      task_result('shard1', TaskState.VERDICT_NO_VERDICT),
      task_result('shard2', TaskState.VERDICT_FAILED),
      task_result('shard2', TaskState.VERDICT_NO_VERDICT),
  ]
  yield api.test(
      'all-failed-test-shards',
      api.properties(child_results=child_results,
                     expected_failed_test_names=['shard1', 'shard2']),
      api.post_process(post_process.DropExpectation),
  )

  child_results = [
      task_result('shard1', TaskState.VERDICT_FAILED),
      task_result('shard1', TaskState.VERDICT_NO_VERDICT),
      task_result('shard2', TaskState.VERDICT_FAILED),
      task_result('shard2', TaskState.VERDICT_PASSED),
  ]
  yield api.test(
      'some-failed-test-shards',
      api.properties(child_results=child_results,
                     expected_failed_test_names=['shard1']),
      api.post_process(post_process.DropExpectation),
  )

  child_results = [
      task_result('shard1', TaskState.VERDICT_FAILED),
      task_result('shard2', TaskState.VERDICT_FAILED),
      task_result('shard1', TaskState.VERDICT_PASSED),
      task_result('shard2', TaskState.VERDICT_PASSED),
  ]
  yield api.test(
      'no-failed-test-shards',
      api.properties(child_results=child_results),
      api.post_process(post_process.DropExpectation),
  )
