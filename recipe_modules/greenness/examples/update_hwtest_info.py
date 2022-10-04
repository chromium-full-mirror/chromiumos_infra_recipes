# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'greenness',
    'skylab',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


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
      api.skylab.test_api.skylab_result(child_results=child_results),
      api.skylab.test_api.skylab_result(child_results=child_results[:2]),
  ]
  api.greenness.update_hwtest_info(results)
  api.assertions.assertEqual(
      api.greenness.greenness_dict['build_target_name'].score, 60)
  api.greenness.publish_step()


def GenTests(api):
  yield api.test('basic')
