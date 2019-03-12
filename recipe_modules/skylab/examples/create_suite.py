# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


DEPS = [
  'recipe_engine/properties',
  'test_plan',
  'skylab'
]

def RunSteps(api):
  for test_plan in api.properties['plan']['test_unit']:
    api.skylab.create_suite('skylab', test_plan)


def GenTests(api):
  yield (api.test('basic') + api.properties(
      plan=api.test_plan.example_test_plan(
          # At least 2 units needed - some behaviors only manifast
          # on second call to create_suite
          api.test_plan.example_hw_unit(test_suite='suite1'),
          api.test_plan.example_hw_unit(test_suite='suite2'))))
