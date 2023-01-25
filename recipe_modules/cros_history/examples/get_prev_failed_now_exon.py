# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions', 'recipe_engine/buildbucket',
    'recipe_engine/json', 'recipe_engine/raw_io', 'cros_history',
    'cros_test_plan', 'exonerate', 'skylab'
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  test_plan = api.cros_test_plan.test_api.generate_test_plan_response
  api.exonerate.load_configs(
      api.cros_history.test_api.mocked_exoneration_config)
  api.cros_history.get_prev_failed_now_exonerable_test_results(test_plan)

  hw_res = api.cros_history.get_failed_now_exonerable_hw_tests_results(
      None, None)
  api.assertions.assertEqual(hw_res, [])


def GenTests(api):
  yield api.test(
      'empty',
      api.buildbucket.simulated_search_results(
          [], step_name=('get previous failed and now exonerable suites.find '
                         'matching builds.buildbucket.search')),
      api.post_process(post_process.StepTextEquals,
                       'get previous failed and now exonerable suites',
                       'found 0 vm suite and 0 hw suite'))
  yield api.test(
      'no_hist',
      api.buildbucket.simulated_search_results(
          [api.cros_history.empty_build_with_test_build_info('min_build')],
          step_name=('get previous failed and now exonerable suites.find '
                     'matching builds.buildbucket.search')),
      api.post_process(post_process.StepTextEquals,
                       'get previous failed and now exonerable suites',
                       'found 0 vm suite and 0 hw suite'))
  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_test_build_ids_properties(['1', '2'],
                                                                ['3', '4'])
      ], step_name=('get previous failed and now exonerable suites.find '
                    'matching builds.buildbucket.search')),
      api.buildbucket.simulated_get_multi([
          api.skylab.test_with_multi_response(
              1234, names=['htarget.hw.bvt-cq'],
              task_state=TaskState(verdict=TaskState.VERDICT_PASSED)),
          api.skylab.test_with_multi_response(
              5679, names=['htarget.hw.bvt-inline'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
          api.skylab.test_with_multi_response(
              9877, names=['htarget.hw.some-other-suite'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
      ], step_name=('get previous failed and now exonerable suites.get '
                    'previous skylab tasks v2.buildbucket.get_multi')),
      api.buildbucket.simulated_get_multi(
          api.cros_history.create_vm_builds(3, 2),
          step_name=('get previous failed and now exonerable suites.get '
                     'tast vm tests from previous run')),
      api.post_process(post_process.StepTextEquals,
                       'get previous failed and now exonerable suites',
                       'found 2 vm suites and 1 hw suite'),
      api.post_process(
          post_process.LogEquals,
          'get previous failed and now exonerable suites', 'exonerable tests',
          ('Test Suites that previously failed but now exonerable \n'
           'VM test suites:\n test_name_4\n test_name_5\n\n'
           'HW test suites:\n htarget.hw.some-other-suite')))

  yield api.test(
      'just_one_vm',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_test_build_ids_properties(['1'], [])],
          step_name=('get previous failed and now exonerable suites.find '
                     'matching builds.buildbucket.search')),
      api.buildbucket.simulated_get_multi(
          api.cros_history.create_vm_builds(0, 1),
          step_name=('get previous failed and now exonerable suites.get '
                     'tast vm tests from previous run')),
      api.post_process(post_process.StepTextEquals,
                       'get previous failed and now exonerable suites',
                       'found 1 vm suite and 0 hw suite'),
      api.post_process(
          post_process.LogEquals,
          'get previous failed and now exonerable suites', 'exonerable tests',
          ('Test Suites that previously failed but now exonerable \n'
           'VM test suites:\n test_name_1\n\nHW test suites:\n ')))

  yield api.test(
      'two_hw',
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_test_build_ids_properties(['1', '2'],
                                                                ['3', '4'])
      ], step_name=('get previous failed and now exonerable suites.find '
                    'matching builds.buildbucket.search')),
      api.buildbucket.simulated_get_multi([
          api.skylab.test_with_multi_response(
              1234, names=['htarget.hw.bvt-cq'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
          api.skylab.test_with_multi_response(
              5679, names=['htarget.hw.bvt-inline'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
          api.skylab.test_with_multi_response(
              9877, names=['htarget.hw.some-other-suite'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
      ], step_name=('get previous failed and now exonerable suites.get '
                    'previous skylab tasks v2.buildbucket.get_multi')),
      api.post_process(post_process.StepTextEquals,
                       'get previous failed and now exonerable suites',
                       'found 0 vm suite and 2 hw suites'),
      api.post_process(
          post_process.LogEquals,
          'get previous failed and now exonerable suites', 'exonerable tests',
          ('Test Suites that previously failed but now exonerable \n'
           'VM test suites:\n \n\nHW test suites:\n '
           'htarget.hw.bvt-cq\n htarget.hw.some-other-suite')))
