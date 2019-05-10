# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_test_plan',
    'skylab',
]


def RunSteps(api):
  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  payload = hw_test_unit.build_payload

  task_id = api.skylab.create_suite(hw_test, payload)
  api.assertions.assertIn(hw_test.suite, task_id)


def GenTests(api):
  yield api.test('basic')
