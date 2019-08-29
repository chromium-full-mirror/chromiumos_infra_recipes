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


def RunSteps(api):
  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.common.display_name = 'my_little_hw_test'

  task = api.skylab.create_recipe(hw_test, hw_test_unit)
  api.assertions.assertEqual(task.test, hw_test)


def GenTests(api):
  yield api.test('basic')
