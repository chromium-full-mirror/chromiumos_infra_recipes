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
  yield (
    api.test('ref_design_test') +
    api.properties(plan={
      'test_unit': [
        api.test_plan.example_hw_unit(test_suite='suite1',
                                      reference_design='ref_design'),
        api.test_plan.example_hw_unit(test_suite='suite2',
                                      reference_design='ref_design'),
      ]
    })
  )

  yield (
    api.test('build_target_test') +
    api.properties(plan={
      'test_unit': [
        api.test_plan.example_hw_unit(test_suite='suite1',
                                      build_target='build_target'),
      ]
    })
  )

  yield (
    api.test('invalid_args_test') +
    api.properties(plan={
      'test_unit': [
        api.test_plan.example_hw_unit(test_suite='suite1'),
      ]
    })
    + api.expect_exception("ValueError")
  )
