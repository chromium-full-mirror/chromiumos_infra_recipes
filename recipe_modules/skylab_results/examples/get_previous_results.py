# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.test_platform.taskstate import TaskState
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest

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
  unit_hw_test = UnitHwTest(unit=hw_test_unit, hw_test=hw_test)
  task = api.skylab_results.test_api.skylab_task(
      bid=1234, url='https://cr-buildbucket.appspot.com/build/1234',
      test=hw_test, unit=hw_test_unit)

  another_hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  another_hw_test = another_hw_test_unit.hw_test_cfg.hw_test[0]
  another_hw_test.common.display_name = 'please_wait_on_me_too'
  another_unit_hw_test_not_present = UnitHwTest(unit=another_hw_test_unit,
                                                hw_test=another_hw_test)

  separate_ctp_unit = api.cros_test_plan.test_api.some_other_hw_test_unit
  separate_ctp_test = separate_ctp_unit.hw_test_cfg.hw_test[0]
  separate_ctp_test.common.display_name = 'wait_on_separate_ctp'
  separate_ctp_unit_hw_test = UnitHwTest(unit=separate_ctp_unit,
                                         hw_test=separate_ctp_test)
  separate_ctp_task = api.skylab_results.test_api.skylab_task(
      bid=5679,
      url='https://cr-buildbucket.appspot.com/build/5679',
      test=separate_ctp_test,
      unit=separate_ctp_unit,
  )

  responses = api.skylab_results.get_previous_results([1234, 5679], [
      unit_hw_test, another_unit_hw_test_not_present, separate_ctp_unit_hw_test
  ])
  api.assertions.assertEqual(len(responses), 2)
  expected_tasks = [r.task.test for r in responses]
  api.assertions.assertEqual(expected_tasks,
                             [task.test, separate_ctp_task.test])


def GenTests(api):
  # These tests use the compressed wire format for actual testing of live code
  #  paths, but also the JSON format so that the expectation files are
  #  human-legible. The JSON path is no longer used in production.
  yield api.test(
      'basic',
      api.buildbucket.simulated_get_multi([
          api.skylab_results.test_with_multi_response(
              1234, names=['please_wait_on_me'],
              task_state=TaskState(verdict=TaskState.VERDICT_PASSED)),
          api.skylab_results.test_with_multi_response(
              5679, names=['wait_on_separate_ctp'],
              task_state=TaskState(verdict=TaskState.VERDICT_PASSED)),
          api.skylab_results.test_with_multi_response(
              9877, names=['non_existent'],
              task_state=TaskState(verdict=TaskState.VERDICT_PASSED)),
      ], step_name='get previous skylab tasks v2.buildbucket.get_multi'),
  )
