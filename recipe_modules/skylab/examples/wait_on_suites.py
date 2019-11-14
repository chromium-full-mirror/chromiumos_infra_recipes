# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_test_plan',
    'skylab',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from google.protobuf import duration_pb2

def RunSteps(api):
  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.common.display_name = 'please_wait_on_me'
  task = api.skylab.test_api.skylab_task(
      id=1234, url=
      'https://ci.chromium.org/p/chromeos/builders/testplatform/cros_test_platform/b8899866335707109280',
      test=hw_test, unit=hw_test_unit)

  another_hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  another_hw_test = another_hw_test_unit.hw_test_cfg.hw_test[0]
  another_hw_test.common.display_name = 'please_wait_on_me_too'
  another_task = api.skylab.test_api.skylab_task(
      id=1234,
      url=
      'https://ci.chromium.org/p/chromeos/builders/testplatform/cros_test_platform/b8899866335707109280',
      test=another_hw_test,
      unit=another_hw_test_unit,
  )

  responses = api.skylab.wait_on_suites([task, another_task],
                                        timeout=duration_pb2.Duration(seconds=3600))
  api.assertions.assertEqual(len(responses), 2)

  expected_tasks = [r.task for r in responses]
  expected_successes = [r.success for r in responses]
  api.assertions.assertEqual(expected_tasks, [task, another_task])
  api.assertions.assertEqual(expected_successes, [True, True])


def GenTests(api):
  yield (api.test('basic') +  #
         api.buildbucket.simulated_collect_output([
             api.skylab.test_with_multi_response(
                 1234, names=['please_wait_on_me', 'please_wait_on_me_too'],
                 success=True),
         ], step_name='collect skylab tasks v2.buildbucket.collect'))

  yield (api.test('build_without_response') +  #
         api.buildbucket.simulated_collect_output([build_pb2.Build(
             id=1234)], step_name='collect skylab tasks v2.buildbucket.collect')
         + api.expect_exception('AssertionError'))
