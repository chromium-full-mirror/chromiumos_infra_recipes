# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_test_plan',
    'skylab',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.taskstate import TaskState
from google.protobuf import duration_pb2

def RunSteps(api):
  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.common.display_name = 'please_wait_on_me'
  task = api.skylab.test_api.skylab_task(
      id=1234, url=
      'https://ci.chromium.org/p/chromeos/builders/testplatform/cros_test_platform/b8899866335707109280',
      test=hw_test, unit=hw_test_unit)

  another_hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  another_hw_test = another_hw_test_unit.hw_test_cfg.hw_test[0]
  another_hw_test.common.display_name = 'please_wait_on_me_too'
  another_task = api.skylab.test_api.skylab_task(
      id=1234,
      url=
      'https://ci.chromium.org/p/chromeos/builders/testplatform/cros_test_platform/b8899866335707109280',
      test=another_hw_test,
      unit=another_hw_test_unit,
  )

  responses = api.skylab.wait_on_suites([task, another_task],
                                        timeout=duration_pb2.Duration(seconds=3600))
  api.assertions.assertEqual(len(responses), 2)

  expected_tasks = [r.task for r in responses]
  expected_statuses = [r.status for r in responses]
  api.assertions.assertEqual(expected_tasks, [task, another_task])


def GenTests(api):
  # These tests use the compressed wire format for actual testing of live code
  #  paths, but also the JSON format so that the expectation files are
  #  human-legible. The JSON path is no longer used in production.
  yield (api.test('basic') +  #
         api.buildbucket.simulated_collect_output([
             api.skylab.test_with_multi_response(
                 1234, names=['please_wait_on_me', 'please_wait_on_me_too'],
                 task_state=TaskState(verdict=TaskState.VERDICT_PASSED)),
         ], step_name='collect skylab tasks v2.buildbucket.collect'))

  yield (api.test('basic_without_JSON_output') +  #
         api.buildbucket.simulated_collect_output([
             api.skylab.test_with_multi_response(
                 1234, names=['please_wait_on_me', 'please_wait_on_me_too'],
                 task_state=TaskState(verdict=TaskState.VERDICT_PASSED),
                 exclude_json=True,
             ),
         ], step_name='collect skylab tasks v2.buildbucket.collect'))

  yield (
      api.test('infra_failure') +  #
      api.buildbucket.simulated_collect_output([
          api.skylab.test_with_multi_response(
              1234, names=['please_wait_on_me', 'please_wait_on_me_too'],
              task_state=TaskState(life_cycle=TaskState.LIFE_CYCLE_CANCELLED)),
      ], step_name='collect skylab tasks v2.buildbucket.collect'))

  yield (api.test('build_without_responses') +  #
         api.buildbucket.simulated_collect_output(
             [build_pb2.Build(id=1234)],
             step_name='collect skylab tasks v2.buildbucket.collect'))
