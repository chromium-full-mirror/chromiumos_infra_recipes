# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'cros_test_plan',
]



def RunSteps(api):
  expected_tests = [
      # HW tests
      api.cros_test_plan.test_api.hw_test_unit.hw_test_cfg.hw_test[0],
      api.cros_test_plan.test_api.another_hw_test_unit.hw_test_cfg.hw_test[0],
      api.cros_test_plan.test_api.non_critical_hw_test_unit(
      ).hw_test_cfg.hw_test[0],
      api.cros_test_plan.test_api.some_other_hw_test_unit.hw_test_cfg
      .hw_test[0],
      # Tast VM tests
      api.cros_test_plan.test_api.direct_tast_vm_test_unit.tast_vm_test_cfg
      .tast_vm_test[0],
      api.cros_test_plan.test_api.direct_tast_vm_test_unit.tast_vm_test_cfg
      .tast_vm_test[1],
      api.cros_test_plan.test_api.tast_vm_informational_test_unit
      .tast_vm_test_cfg.tast_vm_test[0],
      # Tast GCE tests
      api.cros_test_plan.test_api.tast_gce_test_unit.tast_gce_test_cfg
      .tast_gce_test[0],
      api.cros_test_plan.test_api.tast_gce_informational_test_unit
      .tast_gce_test_cfg.tast_gce_test[0],
  ]

  expected_summary = {
      test.common.display_name: test.common.critical for test in expected_tests
  }

  actual_summary = api.cros_test_plan.get_test_plan_summary(
      api.cros_test_plan.test_api.generate_test_plan_response)

  api.assertions.assertCountEqual(actual_summary, expected_summary)


def GenTests(api):
  yield api.test('basic')
