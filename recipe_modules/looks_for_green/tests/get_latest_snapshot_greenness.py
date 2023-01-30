# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine.recipe_api import Property
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'looks_for_green',
]

PROPERTIES = {
    'expected_greenness': Property(default=0),
    'expected_is_snap_orch_green': Property(default=True),
}

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api, expected_greenness, expected_is_snap_orch_green):
  agg_greenness = api.looks_for_green.get_latest_snapshot_greenness()
  api.assertions.assertEqual(expected_greenness, agg_greenness)
  is_snap_orch_green = api.looks_for_green.is_snap_orch_green()
  api.assertions.assertEqual(expected_is_snap_orch_green, is_snap_orch_green)


def GenTests(api):
  output = build_pb2.Build.Output()
  output.properties['greenness'] = {'aggregateMetric': 100}
  yield api.test(
      'success',
      api.properties(expected_greenness=100, expected_is_snap_orch_green=True),
      api.buildbucket.simulated_search_results(
          builds=[build_pb2.Build(id=123, output=output)],
          step_name='checking latest snapshot greenness.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[build_pb2.Build(id=123, output=output)],
          step_name='checking latest snapshot greenness (2).buildbucket.search'
      ),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  output.properties['greenness'] = {'aggregateMetric': 70}
  yield api.test(
      'greenness-below-threshold',
      api.properties(expected_greenness=70, expected_is_snap_orch_green=False),
      api.buildbucket.simulated_search_results(
          builds=[build_pb2.Build(id=123, output=output)],
          step_name='checking latest snapshot greenness.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[build_pb2.Build(id=123, output=output)],
          step_name='checking latest snapshot greenness.buildbucket.search'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  output.properties['greenness'] = {}
  yield api.test(
      'unset-greenness',
      api.properties(expected_greenness=-1, expected_is_snap_orch_green=False),
      api.buildbucket.simulated_search_results(
          builds=[build_pb2.Build(id=123, output=output)],
          step_name='checking latest snapshot greenness.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[build_pb2.Build(id=123, output=output)],
          step_name='checking latest snapshot greenness (2).buildbucket.search'
      ),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'unset-output-props',
      api.properties(expected_greenness=-1, expected_is_snap_orch_green=False),
      api.buildbucket.simulated_search_results(
          builds=[build_pb2.Build(id=123)],
          step_name='checking latest snapshot greenness.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[build_pb2.Build(id=123)],
          step_name='checking latest snapshot greenness (2).buildbucket.search'
      ),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-builds',
      api.properties(expected_greenness=-1, expected_is_snap_orch_green=False),
      api.buildbucket.simulated_search_results(
          builds=[],
          step_name='checking latest snapshot greenness.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[],
          step_name='checking latest snapshot greenness (2).buildbucket.search'
      ),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
