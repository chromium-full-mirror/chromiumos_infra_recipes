# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_plan',
    'git_footers',
    'metadata',
    'skylab',
]

from google.protobuf import duration_pb2

from PB.lab import license as license_pb2
from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties


def RunSteps(api):
  _ = api.skylab.resultdb_elegible_projects
  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.skylab_board = 'specific-model'
  hw_test.common.display_name = 'my_first_little_hwtest'
  unit_hw_test = api.skylab.UnitHwTest(unit=hw_test_unit, hw_test=hw_test)

  another_hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  another_hw_test = another_hw_test_unit.hw_test_cfg.hw_test[0]
  another_hw_test.common.display_name = 'my_second_little_hwtest'
  another_unit_hw_test = api.skylab.UnitHwTest(unit=another_hw_test_unit,
                                               hw_test=another_hw_test)

  non_crit_hw_test_unit = api.cros_test_plan.test_api.non_critical_hw_test_unit
  non_crit_hw_test = non_crit_hw_test_unit.hw_test_cfg.hw_test[0]
  non_crit_hw_test.common.display_name = 'my_third_little_hwtest'
  non_crit_unit_hw_test = api.skylab.UnitHwTest(unit=non_crit_hw_test_unit,
                                                hw_test=non_crit_hw_test)

  hw_test_unit_with_license = api.cros_test_plan.test_api.hw_test_unit
  hw_test_with_license = hw_test_unit_with_license.hw_test_cfg.hw_test[0]
  hw_test_with_license.licenses.extend([
      license_pb2.LICENSE_TYPE_WINDOWS_10_PRO,
      license_pb2.LICENSE_TYPE_MS_OFFICE_STANDARD,
  ])
  unit_hw_test_with_license = api.skylab.UnitHwTest(
      unit=hw_test_unit_with_license, hw_test=hw_test_with_license)

  api.skylab.set_qs_account('a_new_quota_account')

  # HW Test Unit opted-in to running via container
  hw_test_unit_container = api.cros_test_plan.test_api.hw_test_unit
  hw_test_container = hw_test_unit_with_license.hw_test_cfg.hw_test[0]
  hw_test_container.run_via_container = True
  unit_hw_test_container = api.skylab.UnitHwTest(
      unit=hw_test_unit_container,
      hw_test=hw_test_container,
  )

  tasks = api.skylab.schedule_suites(
      [
          unit_hw_test,
          another_unit_hw_test,
          non_crit_unit_hw_test,
          unit_hw_test_with_license,
          unit_hw_test_container,
      ],
      timeout=duration_pb2.Duration(seconds=3600),
      container_metadata=api.metadata.test_api.mock_metadata(target="target"),
  )

  api.assertions.assertEqual(len(tasks), 5)
  api.assertions.assertCountEqual(
      [x.test for x in tasks],
      [
          hw_test,
          another_hw_test,
          non_crit_hw_test,
          hw_test_with_license,
          hw_test_container,
      ],
  )


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/skylab':
                  SkylabProperties(
                      enable_retries=True,
                      enable_container_support=True,
                  )
          }))

  build = api.buildbucket.try_build_message(project='chromeos',
                                            bucket='chromeos',
                                            builder='cq-orchestrator',
                                            experiments={'chromeos.a.b': True})
  yield api.test(
      'experiments', api.buildbucket.build(build),
      api.properties(
          **{
              '$chromeos/skylab':
                  SkylabProperties(resultdb_elegible_projects=['chromeos'])
          }),
      api.git_footers.simulated_get_footers(['chromeos.c.d', 'chromeos.e.f'],
                                            'schedule skylab tests v2'))
