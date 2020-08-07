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
      'has-failed-tests',
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_failed_tests(
              ['my-little-builder', 'your-little-builder'])
      ], 'find matching builds.buildbucket.search'),
      api.properties(**{
          'expected_builder_names':
              ['my-little-builder', 'your-little-builder']
      }))

  yield api.test(
      'no-failed-tests',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_failed_tests([])],
          'find matching builds.buildbucket.search'),
      api.properties(**{'expected_builder_names': []}))

  yield api.test(
      'no-test-failure-value',
      api.buildbucket.simulated_search_results([
          api.cros_history.build_with_passed_tests(
              ['my-little-builder', 'your-little-builder'])
      ], 'find matching builds.buildbucket.search'),
      api.properties(**{'expected_builder_names': []}))
