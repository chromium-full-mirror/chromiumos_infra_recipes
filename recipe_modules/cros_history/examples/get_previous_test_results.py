# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
    'cros_test_plan',
    'skylab_results',
]



def RunSteps(api):

  test_plan = api.cros_test_plan.test_api.generate_test_plan_response
  vm_results, hw_results = api.cros_history.get_previous_test_results(test_plan)
  api.assertions.assertEqual(
      len(vm_results), api.properties.get('expected_vm_results_count'))
  api.assertions.assertEqual(
      len(hw_results), api.properties.get('expected_hw_results_count'))


def GenTests(api):

  yield api.test(
      'no-previous-builds',
      api.buildbucket.simulated_search_results(
          [], step_name=('get previous test results'
                         '.find matching builds.buildbucket.search')),
      api.properties(expected_vm_results_count=0, expected_hw_results_count=0),
  )

  yield api.test(
      'build-without-prev-test-output-property',
      api.buildbucket.simulated_search_results(
          [api.cros_history.empty_build_with_test_build_info('test-builder')],
          step_name=('get previous test results'
                     '.find matching builds.buildbucket.search')),
      api.properties(expected_vm_results_count=0, expected_hw_results_count=0),
  )

  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_test_build_ids_properties(
              hw_ids=['1', '2'], vm_ids=['3', '4'])
      ], step_name=('get previous test results'
                    '.find matching builds.buildbucket.search')),
      api.buildbucket.simulated_get_multi([
          api.skylab_results.test_with_multi_response(
              1234, names=['htarget.hw.bvt-cq'],
              task_state=TaskState(verdict=TaskState.VERDICT_PASSED)),
          api.skylab_results.test_with_multi_response(
              5679, names=['htarget.hw.bvt-inline'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
          api.skylab_results.test_with_multi_response(
              9877, names=['htarget.hw.some-other-suite'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
      ], step_name=('get previous test results'
                    '.get previous skylab tasks v2.buildbucket.get_multi')),
      api.buildbucket.simulated_get_multi(
          api.cros_history.create_vm_builds(num_success=3, num_failure=2),
          step_name=('get previous test results'
                     '.get tast vm tests from previous run')),
      api.properties(expected_vm_results_count=5, expected_hw_results_count=3),
  )
