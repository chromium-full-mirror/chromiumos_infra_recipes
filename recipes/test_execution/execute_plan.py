# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for executing ChromeOS test plan."""

DEPS = [
  'recipe_engine/context',
  'recipe_engine/json',
  'recipe_engine/properties',
  'recipe_engine/step',
  'test_plan',
]

def RunSteps(api):
  step_data = api.json.read(
    'read test plan', api.properties.get('test_plan',''))

  test_plan = step_data.json.output

  if (test_plan is None or len(test_plan.get('test_unit', [])) == 0):
    return

  api.test_plan.run_plan('run plan', test_plan)


def GenTests(api):
  yield api.test('basic')

  yield (
    api.test('empty_plan') +
    api.properties(test_plan='test_plan.json') +
    api.step_data('read test plan', api.json.output({}))
  )

  yield (api.test('test_plan') + api.properties(test_plan='test_plan.json') +
         api.step_data(
             'read test plan',
             api.json.output(
                 api.test_plan.example_test_plan(
                     api.test_plan.example_hw_unit()))))
