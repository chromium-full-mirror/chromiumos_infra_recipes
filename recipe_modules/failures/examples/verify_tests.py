# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'failures',
]


def RunSteps(api):
  results = api.swarming.collect('collect', ['failed-task'])
  api.assertions.assertRaises(api.step.StepFailure, api.failures.verify_tests,
                              results)

  results = api.swarming.collect('collect', ['success-task'])
  api.failures.verify_tests(results)


def GenTests(api):
  success_task_result = api.swarming.task_result('success-task', 'foo')
  failed_task_result = api.swarming.task_result('failed-task', 'bar',
                                                failure=True)
  task_results = [success_task_result, failed_task_result]
  yield (api.test('basic') + api.override_step_data(
      'collect', api.swarming.collect(task_results)))
