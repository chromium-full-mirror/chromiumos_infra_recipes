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
  throttled = api.cros_release.check_stateful_throttling()
  api.step.empty(f"throttled_{throttled}")


def GenTests(api):

  def make_properties(child_statuses=None):
    properties = struct_pb2.Struct()
    if child_statuses is not None:
      properties.update({
          'child_build_info': [{
              'status': status
          } for status in child_statuses]
      })
    return properties

  yield api.test(
      'throttled',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 10 * 3600
              }, output=build_pb2.Build.Output(
                  properties=make_properties(['SUCCESS', 'SUCCESS'])))
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_True'),
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
                  properties=make_properties(['FAILURE', 'FAILURE'])))
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_False'),
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
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_False'),
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
                  properties=make_properties(['SUCCESS'])))
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_False'),
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
                  properties=make_properties(['SUCCESS'])))
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_True'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled-custom-threshold',
      api.time.seed(1600000000),
      api.properties(
          **{'$chromeos/cros_release': {
              'throttling_threshold_percent': 80,
          }}),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 10 * 3600
              }, output=build_pb2.Build.Output(
                  properties=make_properties(
                      ['SUCCESS', 'SUCCESS', 'SUCCESS', 'FAILURE'])))
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_False'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'throttled-custom-threshold',
      api.time.seed(1600000000),
      api.properties(
          **{'$chromeos/cros_release': {
              'throttling_threshold_percent': 80,
          }}),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 10 * 3600
              }, output=build_pb2.Build.Output(
                  properties=make_properties(['SUCCESS'])))
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_True'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled-no-previous-build',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results(
          [], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_False'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled-empty-child-build-info',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              id=123, status=common_pb2.SUCCESS, create_time={
                  'seconds': 1600000000 - 10 * 3600
              }, output=build_pb2.Build.Output(properties=make_properties([])))
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_False'),
      api.post_process(post_process.DropExpectation),
  )
