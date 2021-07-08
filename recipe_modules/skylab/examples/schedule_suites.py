# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_test_plan',
    'skylab',
]

from google.protobuf import duration_pb2

from PB.lab import license as license_pb2
from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties


def RunSteps(api):
  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.common.display_name = 'my_first_little_hwtest'
  unit_hw_test = api.skylab.UnitHwTest(unit=hw_test_unit, hw_test=hw_test)

  another_hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  another_hw_test = another_hw_test_unit.hw_test_cfg.hw_test[0]
  another_hw_test.common.display_name = 'my_second_little_hwtest'
  another_unit_hw_test = api.skylab.UnitHwTest(unit=another_hw_test_unit,
                                               hw_test=another_hw_test)

  hw_test_unit_with_license = api.cros_test_plan.test_api.hw_test_unit
  hw_test_with_license = hw_test_unit_with_license.hw_test_cfg.hw_test[0]
  hw_test_with_license.licenses.extend([
      license_pb2.LICENSE_TYPE_WINDOWS_10_PRO,
      license_pb2.LICENSE_TYPE_MS_OFFICE_STANDARD,
  ])
  unit_hw_test_with_license = api.skylab.UnitHwTest(
      unit=hw_test_unit_with_license, hw_test=hw_test_with_license)

  api.skylab.set_qs_account('a_new_quota_account')

  tasks = api.skylab.schedule_suites(
      [unit_hw_test, another_unit_hw_test, unit_hw_test_with_license],
      timeout=duration_pb2.Duration(seconds=3600))
  api.assertions.assertEqual(len(tasks), 3)
  api.assertions.assertEqual(tasks[0].test, hw_test)
  api.assertions.assertEqual(tasks[1].test, another_hw_test)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{'$chromeos/skylab': SkylabProperties(enable_retries=True)}))
