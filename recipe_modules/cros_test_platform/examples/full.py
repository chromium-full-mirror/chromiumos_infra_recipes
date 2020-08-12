# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
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
  enum_req = EnumerationRequests()
  enum_resp = api.cros_test_platform.enumerate(enum_req)
  # TODO(akeshet): Here and below, mock out json response with non-null
  # response.
  api.assertions.assertEqual(enum_resp, EnumerationResponses())

  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.scheduler_traffic_split(None)
  split_req = SchedulerTrafficSplitRequests()
  split_resp = api.cros_test_platform.scheduler_traffic_split(split_req)
  api.assertions.assertEqual(split_resp, SchedulerTrafficSplitResponses())

  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.skylab_execute(None)
  exec_req = ExecuteRequests()
  exec_resp = api.cros_test_platform.skylab_execute(exec_req)
  api.assertions.assertEqual(exec_resp, ExecuteResponses())

  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.autotest_execute(None)
  exec_req = ExecuteRequests()
  exec_resp = api.cros_test_platform.autotest_execute(exec_req)
  api.assertions.assertEqual(exec_resp, ExecuteResponses())

  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.compute_backfill(None)
  req = ComputeBackfillRequests()
  resp = api.cros_test_platform.compute_backfill(req)
  api.assertions.assertEqual(resp, ComputeBackfillResponses())

  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.execute_luciexe(None)
  resp = api.cros_test_platform.execute_luciexe(ExecuteRequests())
  api.assertions.assertEqual(exec_resp, ExecuteResponses())


def GenTests(api):
  # TODO(crbug.com/1030538): Remove once the default label logic is removed.
  yield api.test('default label')

  yield api.test(
      'custom label',
      api.properties(
          **{'$chromeos/cros_test_platform':
             CrosTestPlatformModuleProperties(
                 version=CrosTestPlatformModuleProperties.Version(
                     cipd_label='some-cipd-label',
                 ))}),
  )
