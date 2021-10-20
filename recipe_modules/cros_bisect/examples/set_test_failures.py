# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_bisect',
    'skylab',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)


def RunSteps(api):
  skylab_success = api.skylab.test_api.skylab_result()
  skylab_failure = api.skylab.test_api.skylab_result(
      task=api.skylab.test_api.skylab_task(
          test=api.skylab.test_api.hw_test(critical=False)),
      status=common_pb2.FAILURE)
  skylab_critical_failure1 = api.skylab.test_api.skylab_result(
      status=common_pb2.FAILURE)
  skylab_critical_failure2 = api.skylab.test_api.skylab_result(
      status=common_pb2.FAILURE)

  # Doesn't output, nothing to report.
  api.cros_bisect.set_test_failures([], 0, 0)
  # Doesn't output, only success.
  api.cros_bisect.set_test_failures([skylab_success], 0, 1)
  # Doesn't output, failure but not critical.
  api.cros_bisect.set_test_failures([skylab_failure], 1, 1)
  # Outputs the failure.
  api.cros_bisect.set_test_failures([skylab_critical_failure1], 1, 1)
  # Outputs two failures and indicates bisection is needed.
  api.cros_bisect.set_test_failures([
      skylab_critical_failure1,
      skylab_success,
      skylab_critical_failure2,
  ], 2, 3)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_bisect':
                  CrosBisectProperties(test_bisection_percent=20,
                                       test_bisection_count=10)
          }),
  )
