# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
    'urls',
]



def vm_build(**kwargs):
  build = build_pb2.Build(**kwargs)
  build.output.properties.update({'name': 'target.vm.suite'})
  return build


def RunSteps(api):
  vm_success = vm_build(status=common_pb2.SUCCESS)
  vm_failure = vm_build(status=common_pb2.FAILURE, critical=common_pb2.NO)
  vm_critical_failure = vm_build(status=common_pb2.FAILURE)

  # Check boolean functions.
  api.assertions.assertFalse(api.failures.is_critical_test_failure(vm_success))

  # Return only critical vm test failures.
  api.assertions.assertFalse(
      api.failures.get_vm_test_results([vm_success]).failures)
  api.assertions.assertFalse(
      api.failures.get_vm_test_results([vm_failure]).failures)
  api.assertions.assertEqual(
      api.failures.get_vm_test_results([vm_critical_failure]).failures, [
          api.failures.Failure(
              'vm test', 'target.vm.suite',
              api.urls.get_vm_test_link_map(vm_critical_failure), True,
              'target.vm.suite')
      ])
  api.assertions.assertEqual(
      api.failures.get_vm_test_results([vm_critical_failure]).successes,
      {'vm test': 0})


def GenTests(api):
  yield api.test('basic')
