# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'failures',
    'skylab',
    'urls',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  skylab_success = api.skylab.test_api.skylab_result()
  skylab_failure = api.skylab.test_api.skylab_result(
      task=api.skylab.test_api.skylab_task(
          test=api.skylab.test_api.hw_test(critical=False)),
      status=common_pb2.FAILURE)
  skylab_critical_failure = api.skylab.test_api.skylab_result(
      status=common_pb2.FAILURE)
  skylab_critical_link_map = api.urls.get_skylab_result_link_map(
      skylab_critical_failure)

  # Check boolean functions first.
  api.assertions.assertFalse(
      api.failures.is_critical_hw_test_failure(skylab_success))
  api.assertions.assertFalse(
      api.failures.is_critical_hw_test_failure(skylab_failure))
  api.assertions.assertTrue(
      api.failures.is_critical_hw_test_failure(skylab_critical_failure))
  api.assertions.assertTrue(
      api.failures.is_critical_test_failure(skylab_critical_failure))

  # Do the obvious thing without baseline tests: raise critical failures only.
  api.assertions.assertFalse(
      api.failures.get_hw_test_failures([skylab_success]))
  api.assertions.assertFalse(
      api.failures.get_hw_test_failures([skylab_failure]))
  api.assertions.assertEqual(
      api.failures.get_hw_test_failures([skylab_critical_failure]), [
          api.failures.Failure('hw test', 'target.hw.bvt-cq',
                               skylab_critical_link_map, True,
                               'target.hw.bvt-cq')
      ])

  # Return fatal failure when critical failure.
  api.assertions.assertEqual(
      api.failures.get_hw_test_failures([skylab_critical_failure]), [
          api.failures.Failure('hw test', 'target.hw.bvt-cq',
                               skylab_critical_link_map, True,
                               'target.hw.bvt-cq')
      ])


def GenTests(api):
  yield api.test('basic')
