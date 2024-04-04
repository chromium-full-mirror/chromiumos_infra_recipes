# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.



# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
]




def RunSteps(api):
  api.assertions.assertCountEqual(api.properties['expected_builder_names'],
                                  api.cros_history.get_test_failure_builders())


def GenTests(api):
  yield api.test(
      'latest-has-no-failed-tests',
      api.buildbucket.simulated_multi_predicates_search_results([
          api.cros_history.build_with_failed_tests(
              ['my-little-builder', 'your-little-builder'], build_id=2,
              create_time=12345),
          api.cros_history.build_with_failed_tests([], build_id=1,
                                                   create_time=12346)
      ], 'find matching builds.buildbucket.search'),
      api.properties(**{'expected_builder_names': []}))

  yield api.test(
      'latest-has-failed-tests',
      api.buildbucket.simulated_multi_predicates_search_results([
          api.cros_history.build_with_failed_tests(
              ['my-little-builder', 'your-little-builder'], build_id=1,
              create_time=12346),
          api.cros_history.build_with_failed_tests(
              ['previous-little-builder'], build_id=2, create_time=12345)
      ], 'find matching builds.buildbucket.search'),
      api.properties(**{
          'expected_builder_names':
              ['my-little-builder', 'your-little-builder']
      }))

  yield api.test(
      'latest-missing-test-summary-field',
      api.buildbucket.simulated_multi_predicates_search_results([
          build_pb2.Build(id=1, create_time=timestamp_pb2.Timestamp(
              seconds=12346), start_time=timestamp_pb2.Timestamp(seconds=12347),
                          end_time=timestamp_pb2.Timestamp(seconds=12348),
                          status=common_pb2.CANCELED),
          api.cros_history.build_with_failed_tests(
              ['previous-little-builder'], build_id=2, create_time=12345)
      ], 'find matching builds.buildbucket.search'),
      api.properties(**{'expected_builder_names': ['previous-little-builder']}))

  yield api.test(
      'no-past-builds',
      api.buildbucket.simulated_multi_predicates_search_results(
          [], 'find matching builds.buildbucket.search'),
      api.properties(**{'expected_builder_names': []}))
