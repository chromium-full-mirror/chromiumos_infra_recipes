# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
]

PROPERTIES = {
    'expected_builder_names': Property(default=[]),
}


def RunSteps(api, expected_builder_names):
  api.assertions.assertItemsEqual(expected_builder_names,
                                  api.cros_history.get_test_failure_builders())


def GenTests(api):
  yield api.test(
      'latest-has-no-failed-tests',
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_failed_tests(
              ['my-little-builder', 'your-little-builder'], build_id=2,
              start_time=12345),
          api.cros_history.build_with_failed_tests([], build_id=1,
                                                   start_time=12346)
      ], 'find matching builds.buildbucket.search'),
      api.properties(**{'expected_builder_names': []}))

  yield api.test(
      'latest-has-failed-tests',
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_failed_tests(
              ['my-little-builder', 'your-little-builder'], build_id=1,
              start_time=12346),
          api.cros_history.build_with_failed_tests(['previous-little-builder'],
                                                   build_id=2, start_time=12345)
      ], 'find matching builds.buildbucket.search'),
      api.properties(**{
          'expected_builder_names':
              ['my-little-builder', 'your-little-builder']
      }))

  yield api.test(
      'no-test-failure-value',
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_passed_tests(
              ['my-little-builder', 'your-little-builder'])
      ], 'find matching builds.buildbucket.search'),
      api.properties(**{'expected_builder_names': []}))

  yield api.test(
      'no-past-builds',
      api.buildbucket.simulated_search_results(
          [], 'find matching builds.buildbucket.search'),
      api.properties(**{'expected_builder_names': []}))
