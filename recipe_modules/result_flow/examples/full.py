# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'result_flow',
]

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.recipe_modules.chromeos.result_flow.result_flow import \
  ResultFlowModuleProperties
from PB.test_platform.result_flow.ctp import CTPRequest
from PB.test_platform.result_flow.test_runner import TestRunnerRequest


def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.result_flow.ctp(None)
  ctp_req = CTPRequest()
  api.result_flow.ctp(ctp_req)

  with api.assertions.assertRaises(ValueError):
    api.result_flow.test_runner(None)
  test_runner_req = TestRunnerRequest()
  api.result_flow.test_runner(test_runner_req)

  with api.assertions.assertRaises(TypeError):
    api.result_flow.publish()
  api.result_flow.publish('foo-proj', 'foo-topic')


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'custom label',
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
