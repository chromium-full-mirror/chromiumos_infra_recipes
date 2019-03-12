# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/properties', 'recipe_engine/swarming', 'test_plan']


def RunSteps(api):
  api.test_plan.run_plan('run plan', api.properties['plan'])


def GenTests(api):
  yield (api.test('invalid_test_env') + api.properties(
      plan=api.test_plan.example_test_plan(
          api.test_plan.example_hw_unit(test_env='invalid'),)))

  yield (api.test('hw_build_target_test') + api.properties(
      plan=api.test_plan.example_test_plan(
          api.test_plan.example_hw_unit(test_suite='suite1'),
          api.test_plan.example_hw_unit(test_suite='suite2'),
      )))

  yield (api.test('vm_test') + api.properties(
      plan=api.test_plan.example_test_plan(
          api.test_plan.example_vm_plan(test_env='vm'),
          api.test_plan.example_vm_plan(test_env='tast_vm'),
      )) + api.step_data('run plan.schedule.execute vm suite test-suite',
                         api.swarming.trigger(['vm-test'])) + api.step_data(
                             'run plan.collect.collect tasks',
                             api.swarming.collect(
                                 [api.swarming.task_result(1, 'vm-test')])))

  yield (api.test('failed_test') + api.properties(
      plan=api.test_plan.example_test_plan(
          api.test_plan.example_vm_plan(test_env='vm', test_suite='suite'),)) +
         api.step_data('run plan.schedule.execute vm suite suite',
                       api.swarming.trigger(['vm-test'])) +
         api.test_plan.simulated_collect_output('run plan.collect',
                                                failure=True))

  yield (api.test('fail_schedule') + api.properties(
      plan=api.test_plan.example_test_plan(
          api.test_plan.example_hw_unit(
              test_env='hw', test_suite='suite1', build_target='build_target',
              image_name='image.bin'),)) + api.test_plan.fail_schedule(
                  'run plan.schedule', test_suite='suite1'))
