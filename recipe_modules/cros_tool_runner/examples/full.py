# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.build.api import container_metadata
from PB.chromiumos.test.api import cros_tool_runner_cli as ctr

from recipe_engine.post_process import DropExpectation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_tool_runner',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def mock_metadata(target='test-target'):
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
    api.cros_tool_runner.pre_process(None)
  pre_process_req = ctr.CrosToolRunnerPreTestRequest()
  api.cros_tool_runner.pre_process(pre_process_req)

  with api.assertions.assertRaises(ValueError):
    api.cros_tool_runner.test(None)
  test_req = ctr.CrosToolRunnerTestRequest()
  api.cros_tool_runner.test(test_req)

  with api.assertions.assertRaises(ValueError):
    api.cros_tool_runner.upload_to_tko(None, 'dummy/results/dir')
  with api.assertions.assertRaises(ValueError):
    api.cros_tool_runner.upload_to_tko('dummy/autotest/dir', None)
  api.cros_tool_runner.upload_to_tko('dummy/autotest/dir', 'dummy/results/dir')

  api.cros_tool_runner.read_dut_hostname()


def GenTests(api):
  yield api.test('basic',
                 api.cros_tool_runner.properties(bot_id='crossk-dut_host_name'))
  yield api.test(
      'running-on-gce-bot',
      api.cros_tool_runner.properties(
          bot_id='chromeos-test-crostfe-us-east1-d-x1-1061-de02'))
  yield (api.test(
      'with-bot-prefix',
      api.cros_tool_runner.properties(
          bot_id='chromeos-test-crostfe-us-east1-d-x1-1061-de02',
          bot_prefix='someprefix')) +
         api.post_process(DropExpectation))
  yield (api.test(
      'basic-with-new-bot-prefix',
      api.cros_tool_runner.properties(bot_id='cros-chromeos1-row2-rack3-host4'))
         + api.post_process(DropExpectation))
  yield (api.test(
      'cloudbots-dut-hostname',
      api.cros_tool_runner.properties(bot_id='cloudbots-prod-0-zxcv')) +
         api.post_process(DropExpectation))
