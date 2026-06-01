# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for stateful throttling in cros_release module."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_release',
]


def RunSteps(api):
  throttled = api.cros_release.check_stateful_throttling()
  api.step.empty(f"throttled_{throttled}")


def GenTests(api):
  yield api.test(
      'throttled',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, status=common_pb2.SUCCESS,
                          create_time={'seconds': 1600000000 - 10 * 3600})
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_True'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-throttled',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, status=common_pb2.SUCCESS,
                          create_time={'seconds': 1600000000 - 30 * 3600})
      ], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_False'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-previous-build',
      api.time.seed(1600000000),
      api.buildbucket.simulated_search_results(
          [], step_name='check stateful throttling'),
      api.post_check(post_process.MustRun, 'throttled_False'),
      api.post_process(post_process.DropExpectation),
  )
