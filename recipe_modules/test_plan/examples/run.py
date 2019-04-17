# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from PB.testplans.generate_test_plan import TestUnit


DEPS = ['recipe_engine/properties', 'recipe_engine/swarming', 'test_plan']

# Inject plan as arg to RunSteps rather than accessing through
# api.properties to avoid 'unhashable object' errors.
PROPERTIES = {'plan': Property()}


def RunSteps(api, plan):
  api.test_plan.run_plan('run plan', plan)


def GenTests(api):
  yield (api.test('invalid_test_unit') +
         api.properties(plan=api.test_plan.example_test_plan(TestUnit())))

  yield (api.test('gce_build_target_test') + api.properties(
      plan=api.test_plan.example_test_plan(
          api.test_plan.example_gce_unit(test_suites=['suite1', 'suite2']))))

  yield (api.test('hw_build_target_test') + api.properties(
      plan=api.test_plan.example_test_plan(
          api.test_plan.example_hw_unit(test_suites=['suite1', 'suite2']))))

  yield (api.test('vm_test') + api.properties(
      plan=api.test_plan.example_test_plan(
          api.test_plan.example_vm_unit(),
          api.test_plan.example_tast_vm_unit(),
      )) + api.step_data('run plan.schedule.build_target.vm.test-suite',
                         api.swarming.trigger(['vm-test'])) + api.step_data(
                             'run plan.collect.vm_swarming_server.com',
                             api.swarming.collect(
                                 [api.swarming.task_result(1, 'vm-test')])))

  yield (
      api.test('failed_test') + api.properties(
          plan=api.test_plan.example_test_plan(
              api.test_plan.example_vm_unit(test_suites=['suite']))) +
      api.step_data('run plan.schedule.build_target.vm.suite',
                    api.swarming.trigger(['vm-test'])) +
      api.test_plan.simulated_collect_output('run plan.collect', failure=True))

  yield (api.test('fail_schedule') + api.properties(
      plan=api.test_plan.example_test_plan(
          api.test_plan.example_hw_unit(
              test_suites=['suite1'], build_target='build_target'))) +
              api.test_plan.fail_schedule(
                  'run plan.schedule.build_target', test_suite='suite1'))
