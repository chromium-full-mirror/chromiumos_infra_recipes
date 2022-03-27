# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_tool_runner',
]

from PB.chromiumos.test.api import cros_tool_runner_cli as ctr


def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.cros_tool_runner.provision(None)
  provision_req = ctr.CrosToolRunnerProvisionRequest()
  api.cros_tool_runner.provision(provision_req)

  with api.assertions.assertRaises(ValueError):
    api.cros_tool_runner.find_tests(None)
  find_tests_req = ctr.CrosToolRunnerTestFinderRequest()
  api.cros_tool_runner.find_tests(find_tests_req)

  with api.assertions.assertRaises(ValueError):
    api.cros_tool_runner.test(None)
  test_req = ctr.CrosToolRunnerTestRequest()
  api.cros_tool_runner.test(test_req)

  with api.assertions.assertRaises(ValueError):
    api.cros_tool_runner.upload_to_tko(None, "dummy/results/dir")
  with api.assertions.assertRaises(ValueError):
    api.cros_tool_runner.upload_to_tko("dummy/autotest/dir", None)
  api.cros_tool_runner.upload_to_tko("dummy/autotest/dir", "dummy/results/dir")

  api.cros_tool_runner.read_dut_hostname()


def GenTests(api):
  yield api.test('basic',
                 api.cros_tool_runner.properties(dut_name='dut_host_name'))
