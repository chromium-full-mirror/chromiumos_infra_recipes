# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'failures',
    'skylab',
]

from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


def RunSteps(api):
  build_success = build_pb2.Build(id=101, status=common_pb2.SUCCESS)
  build_failure = build_pb2.Build(id=202,
                                  status=common_pb2.FAILURE,
                                  critical=common_pb2.NO)
  build_critical_failure = build_pb2.Build(id=303, status=common_pb2.FAILURE)

  vm_success = vm_build(id=404, status=common_pb2.SUCCESS)
  vm_failure = vm_build(id=505,
                        status=common_pb2.FAILURE,
                        critical=common_pb2.NO)
  vm_critical_failure = vm_build(id=606, status=common_pb2.FAILURE)

  moblab_vm_success = moblab_vm_build(id=707, status=common_pb2.SUCCESS)
  moblab_vm_failure = moblab_vm_build(id=808, status=common_pb2.FAILURE,
                                      critical=common_pb2.NO)
  moblab_vm_critical_failure = moblab_vm_build(id=909,
                                               status=common_pb2.FAILURE)

  skylab_success = api.skylab.test_api.skylab_result()
  skylab_failure = api.skylab.test_api.skylab_result(
      task=api.skylab.test_api.skylab_task(
          test=api.skylab.test_api.hw_test(critical=False)),
      success=False)
  skylab_critical_failure = api.skylab.test_api.skylab_result(success=False)

  api.failures.raise_failed_packages([])
  api.assertions.assertRaises(api.step.StepFailure,
                              api.failures.raise_failed_packages,
                              [PackageInfo(package_name='package')])

  # Builds.
  api.failures.raise_failed_builds([build_success])
  api.failures.raise_failed_builds([build_failure])

  api.assertions.assertRaises(api.step.StepFailure,
                              api.failures.raise_failed_builds,
                              [build_critical_failure, build_critical_failure])

  # HW tests.
  api.failures.raise_failed_hw_tests([skylab_success])
  api.failures.raise_failed_hw_tests([skylab_failure])
  api.assertions.assertRaises(
      api.step.StepFailure, api.failures.raise_failed_hw_tests,
      [skylab_critical_failure, skylab_critical_failure])

  # VM tests.
  api.failures.raise_failed_vm_tests([vm_success])
  api.failures.raise_failed_vm_tests([vm_failure])
  api.assertions.assertRaises(api.step.StepFailure,
                              api.failures.raise_failed_vm_tests,
                              [vm_critical_failure, vm_critical_failure])

  # Moblab VM tests
  api.failures.raise_failed_moblab_vm_tests([moblab_vm_success])
  api.failures.raise_failed_moblab_vm_tests([moblab_vm_failure])
  # TODO(evanhernandez): Uncomment this once moblab failures are fatal.
  # api.assertions.assertRaises(api.step.StepFailure,
  #                             api.failures.raise_failed_moblab_vm_tests,
  #                             [moblab_vm_critical_failure,
  #                              moblab_vm_critical_failure])
  api.failures.raise_failed_moblab_vm_tests([moblab_vm_critical_failure])

  # Check boolean functions.
  api.assertions.assertFalse(api.failures.is_build_failure(build_success))
  api.assertions.assertTrue(api.failures.is_build_failure(build_failure))
  api.assertions.assertTrue(
      api.failures.is_build_failure(build_critical_failure))

  api.assertions.assertFalse(
      api.failures.is_critical_build_failure(build_success))
  api.assertions.assertFalse(
      api.failures.is_critical_build_failure(build_failure))
  api.assertions.assertTrue(
      api.failures.is_critical_build_failure(build_critical_failure))

  api.assertions.assertFalse(api.failures.is_hw_test_failure(skylab_success))
  api.assertions.assertTrue(api.failures.is_hw_test_failure(skylab_failure))
  api.assertions.assertTrue(
      api.failures.is_hw_test_failure(skylab_critical_failure))

  api.assertions.assertFalse(
      api.failures.is_critical_hw_test_failure(skylab_success))
  api.assertions.assertFalse(
      api.failures.is_critical_hw_test_failure(skylab_failure))
  api.assertions.assertTrue(
      api.failures.is_critical_hw_test_failure(skylab_critical_failure))

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

  with api.failures.ignore_exceptions():
    api.step('A failed step', ['ls'])


def vm_build(**kwargs):
  build = build_pb2.Build(**kwargs)
  build.output.properties.update({'name': 'target.vm.suite'})
  return build


def moblab_vm_build(**kwargs):
  build = build_pb2.Build(**kwargs)
  build.output.properties.update({'name': 'target.moblab-vm.suite'})
  return build


def GenTests(api):
  yield api.test('basic') + api.step_data('A failed step', retcode=1)
