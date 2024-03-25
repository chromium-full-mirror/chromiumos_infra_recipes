# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.taskstate import TaskState
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_history',
    'cros_test_plan',
    'exonerate',
    'naming',
    'skylab_results',
]



def RunSteps(api):
  test_plan = api.cros_test_plan.test_api.generate_test_plan_response
  api.exonerate.load_configs()
  vms, hws = api.exonerate.get_prev_failed_now_exonerable_test_results(
      test_plan, api.properties['dry_run_exonerate_retried_suites'])

  api.assertions.assertCountEqual(
      api.properties['expected_exonerated_vm_suites'],
      [api.naming.get_vm_test_title(x) for x in vms])
  api.assertions.assertCountEqual(
      api.properties['expected_exonerated_hw_suites'],
      [api.naming.get_skylab_result_title(x) for x in hws])

def GenTests(api):

  yield api.test(
      'no_hist',
      api.properties(dry_run_exonerate_retried_suites=False,
                     expected_exonerated_hw_suites=[],
                     expected_exonerated_vm_suites=[]),
      api.buildbucket.simulated_search_results(
          [api.cros_history.empty_build_with_test_build_info('min_build')],
          step_name=('get previous failed and now exonerable suites'
                     '.get previous test results'
                     '.find matching builds.buildbucket.search')),
      api.post_process(post_process.StepTextEquals,
                       'get previous failed and now exonerable suites',
                       'found 0 vm suite and 0 hw suite'))
  yield api.test(
      'basic',
      api.properties(
          dry_run_exonerate_retried_suites=False,
          expected_exonerated_vm_suites=['test_name_4', 'test_name_5'],
          expected_exonerated_hw_suites=['htarget.hw.some-other-suite'], **{
              '$chromeos/exonerate':
                  ExonerateProperties(enable_exoneration=True)
          }),
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_test_build_ids_properties(['1', '2'],
                                                                ['3', '4'])
      ], step_name=('get previous failed and now exonerable suites'
                    '.get previous test results'
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
      ], step_name=('get previous failed and now exonerable suites'
                    '.get previous test results'
                    '.get previous skylab tasks v2.buildbucket.get_multi')),
      api.buildbucket.simulated_get_multi(
          api.cros_history.create_vm_builds(3, 2),
          step_name=('get previous failed and now exonerable suites'
                     '.get previous test results'
                     '.get tast vm tests from previous run')),
      api.post_process(post_process.StepTextEquals,
                       'get previous failed and now exonerable suites',
                       'found 2 vm suites and 1 hw suite'),
      api.post_process(
          post_process.LogEquals,
          'get previous failed and now exonerable suites', 'exonerable tests',
          ('Test Suites that previously failed but now exonerable \n'
           'VM test suites:\n test_name_4\n test_name_5\n\n'
           'HW test suites:\n htarget.hw.some-other-suite')))

  prev_orch = api.cros_history.build_with_test_build_ids_properties(['1', '2'],
                                                                    ['3', '4'])
  prev_orch.output.properties['passed_tests'] = [
      'htarget.hw.some-other-suite', 'test_name_5'
  ]
  yield api.test(
      'filter-out-previously-exonerated',
      api.properties(
          dry_run_exonerate_retried_suites=False,
          expected_exonerated_hw_suites=[],
          expected_exonerated_vm_suites=['test_name_4'], **{
              '$chromeos/exonerate':
                  ExonerateProperties(enable_exoneration=True)
          }),
      api.buildbucket.simulated_search_results(
          [prev_orch],
          step_name=('get previous failed and now exonerable suites'
                     '.get previous test results'
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
      ], step_name=('get previous failed and now exonerable suites'
                    '.get previous test results'
                    '.get previous skylab tasks v2.buildbucket.get_multi')),
      api.buildbucket.simulated_get_multi(
          api.cros_history.create_vm_builds(3, 2),
          step_name=('get previous failed and now exonerable suites'
                     '.get previous test results'
                     '.get tast vm tests from previous run')),
      api.buildbucket.simulated_search_results([
          prev_orch
      ], 'get previous failed and now exonerable suites.get change test history.find matching builds.buildbucket.search'
                                              ),
      api.post_process(post_process.StepTextEquals,
                       'get previous failed and now exonerable suites',
                       'found 1 vm suite and 0 hw suite'),
      api.post_process(
          post_process.LogEquals,
          'get previous failed and now exonerable suites', 'exonerable tests',
          ('Test Suites that previously failed but now exonerable \n'
           'VM test suites:\n test_name_4\n\n'
           'HW test suites:\n ')))

  dry_run_exonerate_retried_suites = True
  yield api.test(
      'basic_dry_run_exonerate_retried_suites',
      api.properties(
          dry_run_exonerate_retried_suites=dry_run_exonerate_retried_suites,
          expected_exonerated_hw_suites=[], expected_exonerated_vm_suites=[],
          **{
              '$chromeos/exonerate':
                  ExonerateProperties(enable_exoneration=True)
          }),
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_test_build_ids_properties(['1', '2'],
                                                                ['3', '4'])
      ], step_name=('get previous failed and now exonerable suites'
                    '.get previous test results'
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
      ], step_name=('get previous failed and now exonerable suites'
                    '.get previous test results'
                    '.get previous skylab tasks v2.buildbucket.get_multi')),
      api.buildbucket.simulated_get_multi(
          api.cros_history.create_vm_builds(3, 2),
          step_name=('get previous failed and now exonerable suites'
                     '.get previous test results'
                     '.get tast vm tests from previous run')),
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
      api.properties(
          dry_run_exonerate_retried_suites=False,
          expected_exonerated_hw_suites=[],
          expected_exonerated_vm_suites=['test_name_1'], **{
              '$chromeos/exonerate':
                  ExonerateProperties(enable_exoneration=True)
          }),
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_test_build_ids_properties(['1'], [])],
          step_name=('get previous failed and now exonerable suites'
                     '.get previous test results'
                     '.find matching builds.buildbucket.search')),
      api.buildbucket.simulated_get_multi(
          api.cros_history.create_vm_builds(0, 1),
          step_name=('get previous failed and now exonerable suites'
                     '.get previous test results'
                     '.get tast vm tests from previous run')),
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
      api.properties(
          dry_run_exonerate_retried_suites=False,
          expected_exonerated_hw_suites=[
              'htarget.hw.bvt-cq', 'htarget.hw.some-other-suite'
          ], expected_exonerated_vm_suites=[], **{
              '$chromeos/exonerate':
                  ExonerateProperties(enable_exoneration=True)
          }),
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_test_build_ids_properties(['1', '2'],
                                                                ['3', '4'])
      ], step_name=('get previous failed and now exonerable suites'
                    '.get previous test results'
                    '.find matching builds.buildbucket.search')),
      api.buildbucket.simulated_get_multi([
          api.skylab_results.test_with_multi_response(
              1234, names=['htarget.hw.bvt-cq'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
          api.skylab_results.test_with_multi_response(
              5679, names=['htarget.hw.bvt-inline'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
          api.skylab_results.test_with_multi_response(
              9877, names=['htarget.hw.some-other-suite'],
              task_state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases_verdict=TaskState.VERDICT_FAILED),
      ], step_name=('get previous failed and now exonerable suites'
                    '.get previous test results'
                    '.get previous skylab tasks v2.buildbucket.get_multi')),
      api.post_process(post_process.StepTextEquals,
                       'get previous failed and now exonerable suites',
                       'found 0 vm suite and 2 hw suites'),
      api.post_process(
          post_process.LogEquals,
          'get previous failed and now exonerable suites', 'exonerable tests',
          ('Test Suites that previously failed but now exonerable \n'
           'VM test suites:\n \n\nHW test suites:\n '
           'htarget.hw.bvt-cq\n htarget.hw.some-other-suite')))
