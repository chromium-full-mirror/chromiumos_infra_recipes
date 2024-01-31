# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import duration_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_test_plan',
    'skylab',
    'skylab_results',
]



def RunSteps(api):

  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.common.display_name = 'please_wait_on_me'
  task = api.skylab_results.test_api.skylab_task(
      bid=1234,
      url='https://ci.chromium.org/p/chromeos/builders/testplatform/cros_test_platform/b8899866335707109280',
      test=hw_test, unit=hw_test_unit)

  another_hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  another_hw_test = another_hw_test_unit.hw_test_cfg.hw_test[0]
  another_hw_test.common.display_name = 'please_wait_on_me_too'
  another_task = api.skylab_results.test_api.skylab_task(
      bid=1234,
      url='https://ci.chromium.org/p/chromeos/builders/testplatform/cros_test_platform/b8899866335707109280',
      test=another_hw_test,
      unit=another_hw_test_unit,
  )

  separate_ctp_unit = api.cros_test_plan.test_api.some_other_hw_test_unit
  separate_ctp_test = separate_ctp_unit.hw_test_cfg.hw_test[0]
  separate_ctp_test.common.display_name = 'wait_on_separate_ctp'
  separate_ctp_task = api.skylab_results.test_api.skylab_task(
      bid=5679,
      url='https://ci.chromium.org/p/chromeos/builders/testplatform/cros_test_platform/b5678',
      test=separate_ctp_test,
      unit=separate_ctp_unit,
  )

  responses = api.skylab.wait_on_suites(
      [task, another_task, separate_ctp_task],
      timeout=duration_pb2.Duration(seconds=3600))
  api.assertions.assertEqual(len(responses), 3)

  expected_tasks = [r.task for r in responses]
  api.assertions.assertEqual(expected_tasks,
                             [task, another_task, separate_ctp_task])


def GenTests(api):
  # These tests use the compressed wire format for actual testing of live code
  #  paths, but also the JSON format so that the expectation files are
  #  human-legible. The JSON path is no longer used in production.
  yield api.test(
      'basic',
      api.buildbucket.simulated_collect_output([
          api.skylab_results.test_with_multi_response(
              1234, names=['please_wait_on_me', 'please_wait_on_me_too'],
              task_state=TaskState(verdict=TaskState.VERDICT_PASSED)),
          api.skylab_results.test_with_multi_response(
              5679, names=['wait_on_separate_ctp'],
              task_state=TaskState(verdict=TaskState.VERDICT_PASSED)),
      ], step_name='collect skylab tasks v2.buildbucket.collect'),
  )

  yield api.test(
      'basic-without-JSON-output',
      api.buildbucket.simulated_collect_output([
          api.skylab_results.test_with_multi_response(
              1234,
              names=['please_wait_on_me', 'please_wait_on_me_too'],
              task_state=TaskState(verdict=TaskState.VERDICT_PASSED),
              exclude_json=True,
          ),
      ], step_name='collect skylab tasks v2.buildbucket.collect'),
  )

  yield api.test(
      'infra-failure',
      api.buildbucket.simulated_collect_output([
          api.skylab_results.test_with_multi_response(
              1234, names=['please_wait_on_me', 'please_wait_on_me_too'],
              task_state=TaskState(life_cycle=TaskState.LIFE_CYCLE_CANCELLED)),
      ], step_name='collect skylab tasks v2.buildbucket.collect'),
  )

  yield api.test(
      'build-without-responses',
      api.buildbucket.simulated_collect_output(
          [build_pb2.Build(id=1234)],
          step_name='collect skylab tasks v2.buildbucket.collect'),
  )
