# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from collections import OrderedDict
from recipe_engine import post_process

from PB.chromiumos import greenness as greenness_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2, common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'buildbucket_stats',
]


# Test data.
BUILDER_GREENNESS = {
    'eve-snapshot':
        greenness_pb2.AggregateGreenness.Greenness(builder='eve-snapshot',
                                                   build_metric=100, metric=98)
}
BUILD_INPUT = build_pb2.Build.Input()
BUILD_INPUT.gitiles_commit.id = 'bababa'
BUILD_OUTPUT = build_pb2.Build.Output()
BUILD_OUTPUT.properties['greenness'] = {
    'aggregateBuildMetric':
        98,
    'builderGreenness': [{
        'buildMetric': '100',
        'metric': '98',
        'builder': 'eve-snapshot'
    }]
}


def RunSteps(api):
  with api.step.nest('get snapshot greenness') as pres:
    test_end_bbid = api.properties.get('end_bbid')
    builder_greenness = api.buildbucket_stats.get_snapshot_greenness(
        'bababa',
        pres,
        end_bbid=test_end_bbid,
        wait_for_complete=api.properties.get('wait_for_complete'),
    )
    expected_builder_greenness = api.properties.get(
        'expected_builder_greenness', BUILDER_GREENNESS)
    api.assertions.assertEqual(expected_builder_greenness, builder_greenness)


def GenTests(api):
  yield api.test(
      'found',
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, status=common_pb2.SUCCESS,
                          output=BUILD_OUTPUT, input=BUILD_INPUT),
      ], 'get snapshot greenness.buildbucket.search'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'found-after-2-sleeps',
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, output=build_pb2.Build.Output(),
                          input=BUILD_INPUT),
      ], 'get snapshot greenness.buildbucket.search (2)'),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, status=common_pb2.SUCCESS,
                          output=BUILD_OUTPUT, input=BUILD_INPUT),
      ], 'get snapshot greenness.buildbucket.search (3)'),
      api.post_check(post_process.MustRunRE,
                     r'^get snapshot greenness.sleep \d', at_most=2),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'greenness-not-found',
      api.properties(expected_builder_greenness=OrderedDict()),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, status=common_pb2.SUCCESS, input=BUILD_INPUT),
      ], 'get snapshot greenness.buildbucket.search (10)'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-results',
      api.properties(expected_builder_greenness=OrderedDict()),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-end-bbid',
      api.properties(end_bbid=100),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, status=common_pb2.SUCCESS,
                          output=BUILD_OUTPUT, input=BUILD_INPUT),
      ], 'get snapshot greenness.buildbucket.search'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'wait-for-complete',
      api.properties(wait_for_complete=True),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123, status=common_pb2.SUCCESS,
                          output=BUILD_OUTPUT, input=BUILD_INPUT),
      ], 'get snapshot greenness.buildbucket.search'),
      api.post_process(post_process.DropExpectation),
  )
