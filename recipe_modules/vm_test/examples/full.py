# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
    'recipe_engine/swarming',
    'test_plan',
    'vm_test'
]

def RunSteps(api):
  api.vm_test.run_vm_test('vm test', api.test_plan.test_api.example_vm_plan())
  api.vm_test.run_tast_test('tast test', api.test_plan.test_api.example_vm_plan())

def GenTests(api):
  yield (
      api.test('basic') +
      api.step_data('vm test', api.swarming.trigger(['vm-test'])) +
      api.step_data('tast test', api.swarming.trigger(['vm-test']))
  )