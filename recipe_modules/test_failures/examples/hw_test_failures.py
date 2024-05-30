# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from RECIPE_MODULES.chromeos.failures.api import Failure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'test_failures',
    'skylab_results',
    'urls',
]



def RunSteps(api):
  skylab_success = api.skylab_results.test_api.skylab_result()
  skylab_failure = api.skylab_results.test_api.skylab_result(
      task=api.skylab_results.test_api.skylab_task(
          test=api.skylab_results.test_api.hw_test(critical=False)),
      status=common_pb2.FAILURE)
  skylab_critical_failure = api.skylab_results.test_api.skylab_result(
      status=common_pb2.FAILURE)
  skylab_critical_link_map = api.urls.get_skylab_result_link_map(
      skylab_critical_failure)

  # Check boolean functions first.
  api.assertions.assertFalse(
      api.test_failures.is_critical_test_failure(skylab_success))
  api.assertions.assertFalse(
      api.test_failures.is_critical_test_failure(skylab_failure))
  api.assertions.assertTrue(
      api.test_failures.is_critical_test_failure(skylab_critical_failure))

  # Do the obvious thing without baseline tests: raise critical failures only.
  api.assertions.assertFalse(
      api.test_failures.get_hw_test_results([skylab_success]).failures)
  api.assertions.assertFalse(
      api.test_failures.get_hw_test_results([skylab_failure]).failures)
  api.assertions.assertEqual(
      api.test_failures.get_hw_test_results([skylab_critical_failure]).failures, [
          Failure('hw test', 'target.hw.bvt-cq',
                  skylab_critical_link_map, True,
                  'target.hw.bvt-cq')
      ])
  api.assertions.assertEqual(
      api.test_failures.get_hw_test_results([skylab_critical_failure]).successes,
      {'hw test': 0})

  # Return fatal failure when critical failure.
  api.assertions.assertEqual(
      api.test_failures.get_hw_test_results([skylab_critical_failure]).failures, [
          Failure('hw test', 'target.hw.bvt-cq',
                  skylab_critical_link_map, True,
                  'target.hw.bvt-cq')
      ])


def GenTests(api):
  yield api.test('basic')
