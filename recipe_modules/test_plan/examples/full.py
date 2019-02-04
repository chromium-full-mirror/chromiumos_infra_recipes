# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


DEPS = [
  'recipe_engine/properties',
  'test_plan'
]

def RunSteps(api):
  api.test_plan.run('run plan', api.properties['plan'])


def GenTests(api):
  yield (
    api.test('invalid_test_env') +
    api.properties(plan={
      'test_plan': [ api.test_plan.example_hw_unit(test_env='invalid') ]
    })
  )

  yield (
    api.test('hw_ref_design_test') +
    api.properties(plan={
      'test_plan': [
        api.test_plan.example_hw_unit(test_env='hw', test_suite='suite1',
                reference_design='ref_design', image_name='image.bin'),
        api.test_plan.example_hw_unit(test_env='hw', test_suite='suite2',
                reference_design='reference_design', image_name='image.bin'),
      ]
    })
  )

  yield (
    api.test('hw_build_target_test') +
    api.properties(plan={
      'test_plan': [
        api.test_plan.example_hw_unit(test_env='hw', test_suite='suite1',
                build_target='build_target', image_name='image.bin'),
        api.test_plan.example_hw_unit(test_env='hw', test_suite='suite2',
                build_target='build_target', image_name='image.bin'),
      ]
    })
  )

