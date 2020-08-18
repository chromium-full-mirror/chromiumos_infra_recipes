# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_test_platform',
]

from PB.recipe_modules.chromeos.cros_test_platform.cros_test_platform import \
  CrosTestPlatformModuleProperties
from PB.test_platform.steps.enumeration import \
  EnumerationRequests, EnumerationResponses
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequests, SchedulerTrafficSplitResponses
from PB.test_platform.steps.execution import ExecuteRequests, ExecuteResponses
from PB.test_platform.steps.compute_backfill import \
  ComputeBackfillRequests, ComputeBackfillResponses


def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.enumerate(None)
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.scheduler_traffic_split(None)
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.skylab_execute(None)
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.autotest_execute(None)
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.execute_luciexe(None)
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.compute_backfill(None)

  with api.step.nest('callsite-enumerate'):
    api.assertions.assertEqual(
        EnumerationResponses(),
        api.cros_test_platform.enumerate(EnumerationRequests()),
    )
  with api.step.nest('callsite-scheduler-traffic-split'):
    api.assertions.assertEqual(
        SchedulerTrafficSplitResponses(),
        api.cros_test_platform.scheduler_traffic_split(
            SchedulerTrafficSplitRequests()),
    )
  with api.step.nest('callsite-skylab-execute'):
    api.assertions.assertEqual(
        ExecuteResponses(),
        api.cros_test_platform.skylab_execute(ExecuteRequests()),
    )
  with api.step.nest('callsite-autotest-execute'):
    api.assertions.assertEqual(
        ExecuteResponses(),
        api.cros_test_platform.autotest_execute(ExecuteRequests()),
    )
  with api.step.nest('callsite-execute-luciexe'):
    api.assertions.assertEqual(
        ExecuteResponses(),
        api.cros_test_platform.execute_luciexe(ExecuteRequests()),
    )
  with api.step.nest('callsite-compute-backfill'):
    api.assertions.assertEqual(
        ComputeBackfillResponses(),
        api.cros_test_platform.compute_backfill(ComputeBackfillRequests()),
    )


def GenTests(api):
  # TODO(crbug.com/1030538): Remove once the default label logic is removed.
  yield api.test('default label')

  yield api.test(
      'custom label',
      api.properties(
          **{
              '$chromeos/cros_test_platform':
                  CrosTestPlatformModuleProperties(
                      version=CrosTestPlatformModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      ))
          }) +  #
      api.cros_test_platform.set_enumerate_response_json(
          'callsite-enumerate', '{}') +  #
      api.cros_test_platform.set_scheduler_traffic_split_response(
          'callsite-scheduler-traffic-split', SchedulerTrafficSplitResponses())
      +  #
      api.cros_test_platform.set_skylab_execute_response(
          'callsite-skylab-execute', ExecuteResponses()),
      api.cros_test_platform.set_execute_luciexe_response(
          'callsite-execute-luciexe', ExecuteResponses()),
  )
