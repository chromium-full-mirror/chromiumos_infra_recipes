# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module tests the utility method of multi-dut suite generation."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_test_plan',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  hw_test_unit = api.cros_test_plan.test_api.multi_dut_hw_test_unit
  api.assertions.assertGreater(
      len(hw_test_unit.hw_test_cfg.hw_test[0].companions), 1)
  hw_test_unit = api.cros_test_plan.test_api.multi_dut_no_android_hw_test_unit
  api.assertions.assertGreater(
      len(hw_test_unit.hw_test_cfg.hw_test[0].companions), 0)


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.DropExpectation))
