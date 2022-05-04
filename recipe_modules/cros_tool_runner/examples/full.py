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

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from PB.chromiumos.test.api import cros_tool_runner_cli as ctr
from PB.chromiumos.build.api import container_metadata


def mock_metadata(target="test-target"):
  metadata = container_metadata.ContainerMetadata(
      containers={
          target:
              container_metadata.ContainerImageMap(
                  images={
                      'cros-test':
                          container_metadata.ContainerImageInfo(
                              repository=container_metadata.GcrRepository(
                                  hostname='gcr.io',
                                  project='chromeos-bot',
                              ),
                              name='cros-test',
                              digest='sha256:3e36d3622f5adad01080cc2120bb72c0714ecec6118eb9523586410b7435ae80',
                              tags=[
                                  '8835841547076258945',
                                  'amd64-generic-release.R96-1.2.3',
                              ],
                          ),
                  }),
      })
  return metadata


def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.cros_tool_runner.ensure_cros_tool_runner()
  api.cros_tool_runner.container_metadata = mock_metadata()

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
