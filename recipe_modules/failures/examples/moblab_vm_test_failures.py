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

def moblab_vm_build(**kwargs):
  build = build_pb2.Build(**kwargs)
  build.output.properties.update({'name': 'target.moblab-vm.suite'})
  return build

def RunSteps(api):
  moblab_vm_success = moblab_vm_build(status=common_pb2.SUCCESS)
  moblab_vm_failure = moblab_vm_build(status=common_pb2.FAILURE,
                                      critical=common_pb2.NO)
  moblab_vm_critical_failure = moblab_vm_build(status=common_pb2.FAILURE)

  # Check boolean functions.
  api.assertions.assertFalse(
      api.failures.is_moblab_vm_test_failure(moblab_vm_success))
  api.assertions.assertTrue(
      api.failures.is_moblab_vm_test_failure(moblab_vm_failure))
  api.assertions.assertTrue(
      api.failures.is_moblab_vm_test_failure(moblab_vm_critical_failure))

  api.assertions.assertFalse(
      api.failures.is_critical_moblab_vm_test_failure(moblab_vm_success))
  api.assertions.assertFalse(
      api.failures.is_critical_moblab_vm_test_failure(moblab_vm_failure))
  api.assertions.assertTrue(
      api.failures.is_critical_moblab_vm_test_failure(
          moblab_vm_critical_failure))

  # Return only critical Moblab VM test failures.
  api.assertions.assertFalse(
      api.failures.get_moblab_vm_test_failures([moblab_vm_success]))
  api.assertions.assertFalse(
      api.failures.get_moblab_vm_test_failures([moblab_vm_failure]))
  api.assertions.assertEqual(
      api.failures.get_moblab_vm_test_failures([moblab_vm_critical_failure]),
      [api.failures.Failure('moblab vm test', 'target.moblab-vm.suite', True)])

def GenTests(api):
  yield api.test('basic')
