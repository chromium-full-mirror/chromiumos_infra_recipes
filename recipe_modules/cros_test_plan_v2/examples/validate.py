# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the cros_test_plan_v2.validation function."""

from PB.recipe_modules.chromeos.cros_test_plan_v2.cros_test_plan_v2 import CrosTestPlanV2Properties

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_test_plan_v2',
]


def RunSteps(api):
  testdir = api.path.mkdtemp()
  api.cros_test_plan_v2.validate(testdir)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'with-validate-tag-criteria-non-empty',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(
                      validate_tag_criteria_non_empty=True),
          }),
  )
