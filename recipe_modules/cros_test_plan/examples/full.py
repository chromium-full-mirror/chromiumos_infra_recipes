# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build

DEPS = [
    'recipe_engine/assertions',
    'cros_test_plan',
]


def RunSteps(api):
  test_plan = api.cros_test_plan.generate([Build()])

  # Sanity check that we can access some slots. This is partially
  # meant to serve as an example.
  hw_tests = test_plan.hw
  api.assertions.assertTrue(hw_tests)

  vm_tests = test_plan.vm
  api.assertions.assertTrue(vm_tests)

  # Make sure all slots line up with test data.
  for slot in api.cros_test_plan.TestPlan.__slots__:
    test_api_slot = '%s_test_unit' % slot

    # Double check the test_api defines test data for all slots.
    api.assertions.assertTrue(
        hasattr(api.cros_test_plan.test_api, test_api_slot),
        msg='No test data found for test type %s. Please add it to '
        'recipe_modules/cros_test_plan/test_api.py now.' % slot)

    # Now verify the slots return the correct test data.
    api.assertions.assertEqual(
        getattr(test_plan, slot),
        [getattr(api.cros_test_plan.test_api, test_api_slot)])


def GenTests(api):
  yield api.test('basic')
