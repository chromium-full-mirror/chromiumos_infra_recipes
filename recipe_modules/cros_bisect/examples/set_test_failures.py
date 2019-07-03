# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_bisect',
    'skylab',
]

def RunSteps(api):
  skylab_success = api.skylab.test_api.skylab_result()
  skylab_failure = api.skylab.test_api.skylab_result(
      task=api.skylab.test_api.skylab_task(
          test=api.skylab.test_api.hw_test(critical=False)), success=False)
  skylab_critical_failure1 = api.skylab.test_api.skylab_result(success=False)
  skylab_critical_failure2 = api.skylab.test_api.skylab_result(success=False)

  # Doesn't output, nothing to report.
  api.cros_bisect.set_test_failures([])
  # Doesn't output, only success.
  api.cros_bisect.set_test_failures([skylab_success])
  # Doesn't output, failure but not critical.
  api.cros_bisect.set_test_failures([skylab_failure])
  # Outputs the failure.
  api.cros_bisect.set_test_failures([skylab_critical_failure1])
  # Outputs two failures.
  api.cros_bisect.set_test_failures([
      skylab_critical_failure1,
      skylab_success,
      skylab_critical_failure2,
  ])


def GenTests(api):
  yield api.test('basic')
