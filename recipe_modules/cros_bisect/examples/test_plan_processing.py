# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_bisect',
]

from recipe_engine.config import List
from recipe_engine.recipe_api import Property

from PB.chromiumos.common import PackageInfo

from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)

from google.protobuf import json_format as jsonpb


def RunSteps(api):
  # This verifies that the HwTest which were split out into separate test
  # failures get correctly regrouped by their TestSuiteCommon.
  test_plan = api.cros_bisect.get_test_plan()
  api.assertions.assertEqual(len(test_plan.hw_test_units), 2)
  for hw_test_unit in test_plan.hw_test_units:
    if hw_test_unit.common.build_target.name == 'foo':
      api.assertions.assertEqual(len(hw_test_unit.hw_test_cfg.hw_test), 1)
    elif hw_test_unit.common.build_target.name == 'bar':
      api.assertions.assertEqual(len(hw_test_unit.hw_test_cfg.hw_test), 2)
    else: # pragma: no cover
      api.assertions.fail('Expected to find build_target name foo or bar.')

def GenTests(api):
  hw_test_unit1 = api.cros_bisect.hw_test_unit('foo')
  hw_test_unit2 = api.cros_bisect.hw_test_unit('bar')
  hw_test_unit3 = api.cros_bisect.hw_test_unit('bar')

  yield (api.test('with-test-plan') +  #
         api.properties(
             **{'$chromeos/cros_bisect':
                CrosBisectProperties(test={'hw_test_failures': [
                    CrosBisectProperties.TestFailures.TestFailure(
                        test_spec=jsonpb.MessageToJson(hw_test_unit1)),
                    CrosBisectProperties.TestFailures.TestFailure(
                        test_spec=jsonpb.MessageToJson(hw_test_unit2)),
                    CrosBisectProperties.TestFailures.TestFailure(
                        test_spec=jsonpb.MessageToJson(hw_test_unit3)),
                ]})}
         ))
