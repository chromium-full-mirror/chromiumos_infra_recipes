# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.recipe_modules.chromeos.result_flow.result_flow import ResultFlowModuleProperties
from PB.test_platform.result_flow.ctp import CTPRequest
from PB.test_platform.result_flow.test_runner import TestRunnerRequest

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'result_flow',
]



def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.result_flow.pipe_ctp_data(None)
  ctp_req = CTPRequest()
  api.result_flow.pipe_ctp_data(ctp_req)

  with api.assertions.assertRaises(ValueError):
    api.result_flow.pipe_test_runner_data(None)
  test_runner_req = TestRunnerRequest()
  api.result_flow.pipe_test_runner_data(test_runner_req)

  with api.assertions.assertRaises(TypeError):
    api.result_flow.publish()
  with api.assertions.assertRaises(ValueError):
    api.result_flow.publish('foo-proj', 'foo-topic', 'invalid-build-type')
  api.result_flow.publish('foo-proj', 'foo-topic', 'ctp')
  api.result_flow.publish('foo-proj', 'foo-topic', 'test_runner',
                          parent_uid='foo-parent-uid',
                          should_poll_for_completion=True)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'custom-label',
      api.buildbucket.build(Build(id=123456789)),
      api.properties(
          **{
              '$chromeos/result_flow':
                  ResultFlowModuleProperties(
                      version=ResultFlowModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      ))
          }),
  )
