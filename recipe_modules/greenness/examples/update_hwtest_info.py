# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'greenness',
    'skylab_results',
]



def RunSteps(api):
  pass_state = TaskState(verdict=TaskState.VERDICT_PASSED)
  fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
  child_results_1 = [
      ExecuteResponse.TaskResult(
          name='test1-shard-1',
          state=pass_state,
      ),
      ExecuteResponse.TaskResult(
          name='test1-shard-2',
          state=fail_state,
      ),
      ExecuteResponse.TaskResult(
          name='test1-shard-3',
          state=pass_state,
      ),
  ]
  child_results_2 = [
      ExecuteResponse.TaskResult(
          name='test2-shard-1',
          state=fail_state,
      ),
      ExecuteResponse.TaskResult(
          name='test2-shard-1',
          state=pass_state,
      ),
      ExecuteResponse.TaskResult(
          name='test2-shard-2',
          state=fail_state,
      ),
      ExecuteResponse.TaskResult(
          name='test2-shard-2',
          state=fail_state,
      ),
      ExecuteResponse.TaskResult(
          name='test2-shard-3',
          state=pass_state,
      ),
  ]
  results = [
      api.skylab_results.test_api.skylab_result(child_results=child_results_1),
      api.skylab_results.test_api.skylab_result(child_results=child_results_2),
  ]
  api.greenness.update_hwtest_info(results)
  api.assertions.assertEqual(
      api.greenness.builder_greenness_dict['builder_name'].score, 66)
  api.greenness.publish_step()


def GenTests(api):
  yield api.test('basic')
