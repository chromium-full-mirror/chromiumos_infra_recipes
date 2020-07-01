# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'result_flow',
]

from PB.recipe_modules.chromeos.result_flow.result_flow import \
  ResultFlowModuleProperties
from PB.test_platform.result_flow.ctp import CTPRequest


def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.result_flow.ctp(None)
  ctp_req = CTPRequest()
  api.result_flow.ctp(ctp_req)

  # TODO(lxn@): replace below to the test for "test_runner" sub-command.
  # Run ctp() again to cover the case when _cmd is not None.
  api.result_flow.ctp(CTPRequest())


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'custom label',
      api.properties(
          **{
              '$chromeos/result_flow':
                  ResultFlowModuleProperties(
                      version=ResultFlowModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      ))
          }),
  )
