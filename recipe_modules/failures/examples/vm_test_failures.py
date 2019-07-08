# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

def vm_build(**kwargs):
  build = build_pb2.Build(**kwargs)
  build.output.properties.update({'name': 'target.vm.suite'})
  return build

def RunSteps(api):
  vm_success = vm_build(id=404, status=common_pb2.SUCCESS)
  vm_failure = vm_build(id=505,
                        status=common_pb2.FAILURE,
                        critical=common_pb2.NO)
  vm_critical_failure = vm_build(id=606, status=common_pb2.FAILURE)

  # Check boolean functions.
  api.assertions.assertFalse(api.failures.is_vm_test_failure(vm_success))
  api.assertions.assertTrue(api.failures.is_vm_test_failure(vm_failure))
  api.assertions.assertTrue(
      api.failures.is_vm_test_failure(vm_critical_failure))

  api.assertions.assertFalse(
      api.failures.is_critical_vm_test_failure(vm_success))
  api.assertions.assertFalse(
      api.failures.is_critical_vm_test_failure(vm_failure))
  api.assertions.assertTrue(
      api.failures.is_critical_vm_test_failure(vm_critical_failure))

  # Raise on critical vm test failures.
  api.failures.raise_failed_vm_tests([vm_success])
  api.failures.raise_failed_vm_tests([vm_failure])
  api.assertions.assertRaises(api.step.StepFailure,
                              api.failures.raise_failed_vm_tests,
                              [vm_critical_failure, vm_critical_failure])

def GenTests(api):
  yield api.test('basic')
