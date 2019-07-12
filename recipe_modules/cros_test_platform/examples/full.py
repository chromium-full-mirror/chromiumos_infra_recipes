# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_test_platform',
]

from PB.test_platform.steps.enumeration import \
  EnumerationRequest, EnumerationResponse
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequest,SchedulerTrafficSplitResponse
from PB.test_platform.steps.execution import ExecuteRequest, ExecuteResponse


def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.enumerate(None)
  enum_req = EnumerationRequest()
  enum_resp = api.cros_test_platform.enumerate(enum_req)
  # TODO(akeshet): Here and below, mock out json response with non-null
  # response.
  api.assertions.assertEqual(enum_resp, EnumerationResponse())

  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.scheduler_traffic_split(None)
  split_req = SchedulerTrafficSplitRequest()
  split_resp = api.cros_test_platform.scheduler_traffic_split(split_req)
  api.assertions.assertEqual(split_resp, SchedulerTrafficSplitResponse())

  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.skylab_execute(None)
  exec_req = ExecuteRequest()
  exec_resp = api.cros_test_platform.skylab_execute(exec_req)
  api.assertions.assertEqual(exec_resp, ExecuteResponse())

  with api.assertions.assertRaises(ValueError):
    api.cros_test_platform.autotest_execute(None)
  exec_req = ExecuteRequest()
  exec_resp = api.cros_test_platform.autotest_execute(exec_req)
  api.assertions.assertEqual(exec_resp, ExecuteResponse())


def GenTests(api):
  yield api.test('basic')
