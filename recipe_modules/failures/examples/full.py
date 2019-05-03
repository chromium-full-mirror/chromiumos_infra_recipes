# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'failures',
    'test_plan',
]

from PB.chromiumos.common import PackageInfo


def RunSteps(api):
  api.failures.raise_failed_packages([])
  api.assertions.assertRaises(api.step.StepFailure,
                              api.failures.raise_failed_packages,
                              [PackageInfo(package_name='package')])

  task_results = api.swarming.collect(
      'collect test results.vm_swarming_server.com', ['task'])
  api.failures.verify_tests(task_results)


def GenTests(api):
  yield api.test('basic')

  yield (api.test('with_verify_task_result_success') +
         api.test_plan.simulated_collect_output('collect test results',
                                                failure=False))

  yield (api.test('with_verify_task_result_failure') +
         api.test_plan.simulated_collect_output('collect test results',
                                                failure=True))
