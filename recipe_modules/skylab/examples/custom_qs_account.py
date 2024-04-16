# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test custom_qs_account functionality."""

from google.protobuf import duration_pb2

from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/json',
    'recipe_engine/properties',
    'cros_test_plan',
    'git_footers',
    'metadata',
    'skylab',
]



def RunSteps(api):
  builder_name = 'test-board-release-main'

  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test_unit.common.builder_name = builder_name
  hw_test_unit.common.build_target.name = 'foo'
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.skylab_board = 'specific-model'
  hw_test.common.display_name = 'my_first_little_hwtest'
  unit_hw_test = UnitHwTest(unit=hw_test_unit, hw_test=hw_test)

  another_hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  another_hw_test_unit.common.builder_name = builder_name
  another_hw_test_unit.common.build_target.name = 'bar'
  another_hw_test = another_hw_test_unit.hw_test_cfg.hw_test[0]
  another_hw_test.common.display_name = 'my_second_little_hwtest'
  another_unit_hw_test = UnitHwTest(unit=another_hw_test_unit,
                                    hw_test=another_hw_test)

  tasks = api.skylab.schedule_suites(
      [
          unit_hw_test,
          another_unit_hw_test,
      ],
      timeout=duration_pb2.Duration(seconds=3600),
  )

  api.assertions.assertEqual(len(tasks), 2)
  api.assertions.assertCountEqual(
      [x.test for x in tasks],
      [
          hw_test,
          another_hw_test,
      ],
  )


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/skylab':
                  SkylabProperties(
                      custom_qs_account='release-low-prio',
                      custom_qs_account_build_target_allowlist=['bar'],
                  )
          }), api.buildbucket.ci_build(builder='release-main-orchestrator'))
