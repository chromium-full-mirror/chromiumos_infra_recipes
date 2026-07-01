# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for stateful throttling in cros_release module."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from google.protobuf import struct_pb2
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_release',
]


def RunSteps(api):
  throttled, build = api.cros_release.check_stateful_throttling()
  build_id = build.id if build else None
  api.step.empty(f"throttled_{throttled}_by_{build_id}")


def GenTests(api):

  def make_properties(success_ratio=None):
    properties = struct_pb2.Struct()
    if success_ratio is not None:
      total = 10
      success_count = int(total * success_ratio / 100.0)
      child_info = []
      for i in range(total):
        status = 'SUCCESS' if i < success_count else 'FAILURE'
        child_info.append({
            'builder': {
                'builder': f'builder-release-{i}',
                'bucket': 'release'
            },
            'status': status,
        })

      # Add testplatform builds that failed to test filtering
      child_info.append({
          'builder': {
              'builder': 'builder-testplatform',
              'bucket': 'testplatform'
          },
          'status': 'FAILURE',
      })
      properties.update({'child_build_info': child_info})
    return properties

  yield api.test(
      'throttled',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 10 * 3600
              }, output=build_pb2.Build.Output(
                  properties=make_properties(success_ratio=90)))
      ], step_name='check stateful throttling.search builds'),
      api.post_check(post_process.MustRun, 'throttled_True_by_123'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled-low-success-rate',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 10 * 3600
              }, output=build_pb2.Build.Output(
                  properties=make_properties(success_ratio=70)))
      ], step_name='check stateful throttling.search builds'),
      api.post_check(post_process.MustRun, 'throttled_False_by_None'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled-previous-was-throttled',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS,
              create_time={'seconds': 1600000000 - 10 * 3600},
              output=build_pb2.Build.Output(properties=make_properties(None)))
      ], step_name='check stateful throttling.search builds'),
      api.post_check(post_process.MustRun, 'throttled_False_by_None'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled-too-old',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 30 * 3600
              }, output=build_pb2.Build.Output(
                  properties=make_properties(success_ratio=100)))
      ], step_name='check stateful throttling.search builds'),
      api.post_check(post_process.MustRun, 'throttled_False_by_None'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'throttled-with-multiple-previous',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=124, status=common_pb2.SUCCESS,
              create_time={'seconds': 1600000000 - 10 * 3600},
              output=build_pb2.Build.Output(properties=make_properties(None))),
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 15 * 3600
              }, output=build_pb2.Build.Output(
                  properties=make_properties(success_ratio=100)))
      ], step_name='check stateful throttling.search builds'),
      api.post_check(post_process.MustRun, 'throttled_True_by_123'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled-custom-threshold',
      api.time.seed(1600000000),
      api.properties(
          **{'$chromeos/cros_release': {
              'throttling_threshold_percent': 90,
          }}),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 10 * 3600
              }, output=build_pb2.Build.Output(
                  properties=make_properties(success_ratio=80)))
      ], step_name='check stateful throttling.search builds'),
      api.post_check(post_process.MustRun, 'throttled_False_by_None'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'throttled-custom-threshold',
      api.time.seed(1600000000),
      api.properties(
          **{'$chromeos/cros_release': {
              'throttling_threshold_percent': 90,
          }}),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 10 * 3600
              }, output=build_pb2.Build.Output(
                  properties=make_properties(success_ratio=100)))
      ], step_name='check stateful throttling.search builds'),
      api.post_check(post_process.MustRun, 'throttled_True_by_123'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled-no-previous-build',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results(
          [], step_name='check stateful throttling.search builds'),
      api.post_check(post_process.MustRun, 'throttled_False_by_None'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled-all-children-testplatform',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 10 * 3600
              }, output=build_pb2.Build.Output(
                  properties={
                      'child_build_info': [{
                          'builder': {
                              'builder': 'builder-testplatform',
                              'bucket': 'testplatform'
                          },
                          'status': 'SUCCESS',
                      }]
                  }))
      ], step_name='check stateful throttling.search builds'),
      api.post_check(post_process.MustRun, 'throttled_False_by_None'),
      api.post_process(post_process.DropExpectation),
  )
