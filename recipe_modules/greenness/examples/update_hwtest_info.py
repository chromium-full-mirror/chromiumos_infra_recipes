# -*- coding: utf-8 -*-
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
  child_results = [
      ExecuteResponse.TaskResult(
          name='test1',
          state=pass_state,
      ),
      ExecuteResponse.TaskResult(
          name='test2',
          state=fail_state,
      ),
      ExecuteResponse.TaskResult(
          name='test3',
          state=pass_state,
      ),
  ]
  results = [
      api.skylab_results.test_api.skylab_result(child_results=child_results),
      api.skylab_results.test_api.skylab_result(
          child_results=child_results[:2]),
  ]
  api.greenness.update_hwtest_info(results)
  api.assertions.assertEqual(
      api.greenness.greenness_dict['build_target_name'].score, 60)
  api.greenness.publish_step()


def GenTests(api):
  yield api.test('basic')
