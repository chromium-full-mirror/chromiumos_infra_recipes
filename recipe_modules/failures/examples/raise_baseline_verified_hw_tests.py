# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
    'skylab',
]


def RunSteps(api):
  skylab_success = api.skylab.test_api.skylab_result()
  skylab_failure = api.skylab.test_api.skylab_result(
      task=api.skylab.test_api.skylab_task(
          test=api.skylab.test_api.hw_test(critical=False)), success=False)
  skylab_critical_failure = api.skylab.test_api.skylab_result(success=False)
  # Maintain the same functionality when no baseline tests are run.
  api.failures.raise_failed_hw_tests([skylab_success])
  api.failures.raise_failed_hw_tests([skylab_failure])
  api.assertions.assertRaises(
      api.step.StepFailure,
      api.failures.raise_failed_hw_tests,
      [skylab_critical_failure, skylab_critical_failure])
  # There's a failure in both tests.
  api.failures.raise_failed_hw_tests(
      [skylab_critical_failure], [skylab_critical_failure])
  # Baseline tests passed but patch tests failed.
  api.assertions.assertRaises(
      api.step.StepFailure,
      api.failures.raise_failed_hw_tests,
      [skylab_critical_failure], [skylab_success])


def GenTests(api):
  yield api.test('basic')
