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

  # Check boolean functions first.
  api.assertions.assertFalse(api.failures.is_hw_test_failure(skylab_success))
  api.assertions.assertTrue(api.failures.is_hw_test_failure(skylab_failure))
  api.assertions.assertTrue(
      api.failures.is_hw_test_failure(skylab_critical_failure))

  api.assertions.assertFalse(
      api.failures.is_critical_hw_test_failure(skylab_success))
  api.assertions.assertFalse(
      api.failures.is_critical_hw_test_failure(skylab_failure))
  api.assertions.assertTrue(
      api.failures.is_critical_hw_test_failure(skylab_critical_failure))

  # Do the obvious thing without baseline tests: raise critical failures only.
  api.failures.raise_failed_hw_tests([skylab_success])
  api.failures.raise_failed_hw_tests([skylab_failure])
  api.assertions.assertRaises(
      api.step.StepFailure,
      api.failures.raise_failed_hw_tests,
      [skylab_critical_failure, skylab_critical_failure])

  # Don't raise when critical failure also fails baseline.
  api.failures.raise_failed_hw_tests(
      [skylab_critical_failure],
      baseline_hw_tests=[skylab_critical_failure])

  # Raise when critical failure does not fail baseline.
  api.assertions.assertRaises(
      api.step.StepFailure,
      api.failures.raise_failed_hw_tests,
      [skylab_critical_failure],
      baseline_hw_tests=[skylab_success])


def GenTests(api):
  yield api.test('basic')
