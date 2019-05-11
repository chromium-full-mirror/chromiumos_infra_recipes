# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['test_plan', 'skylab']


def RunSteps(api):
  # Generate plan here rather than GenTests to avoid "unhashable object" errors.
  test_plan = api.test_plan.test_api.example_test_plan(
      api.test_plan.test_api.example_hw_unit(test_suites=['suite1', 'suite2']))

  for test_unit in test_plan.test_unit:
    api.skylab.create_suites('test', test_unit)


def GenTests(api):
  test_unit = api.test_plan.example_hw_unit(test_suites=['suite1', 'suite2'])

  yield (
      api.test('basic') + api.skylab.simulated_create_suites('test', test_unit))
