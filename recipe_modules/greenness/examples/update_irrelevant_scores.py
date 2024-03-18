# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the update_irrelevant_scores function."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2, common as common_pb2
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_tags',
    'greenness',
    'test_util',
]

# The initial search for the previous snapshot build returns an in-progress
# snapshot build that only has build metrics set.
BUILD_INPUT = build_pb2.Build.Input()
BUILD_INPUT.gitiles_commit.id = 'ababab'
BUILD_OUTPUT_WITH_BUILD_METRIC = build_pb2.Build.Output()
BUILD_OUTPUT_WITH_BUILD_METRIC.properties['greenness'] = {
    'builderGreenness': [
        {
            'buildMetric': '98',
            'builder': 'eve-postsubmit'
        },
        {
            'context': 'IRRELEVANT',
            'builder': 'eve-kernelnext-postsubmit'
        },
    ]
}
LAST_SNAPSHOT_WITH_BUILD_METRIC = build_pb2.Build(
    id=123,
    status=common_pb2.STARTED,
    output=BUILD_OUTPUT_WITH_BUILD_METRIC,
    input=BUILD_INPUT,
)

# The second search returns a completed snapshot build with all metrics set.
BUILD_OUTPUT_WITH_ALL_METRICS = build_pb2.Build.Output()
BUILD_OUTPUT_WITH_ALL_METRICS.properties['greenness'] = {
    'builderGreenness': [
        {
            'buildMetric': '98',
            'metric': '78',
            'builder': 'eve-postsubmit'
        },
        {
            'context': 'IRRELEVANT',
            'builder': 'eve-kernelnext-postsubmit'
        },
    ]
}
LAST_SNAPSHOT_WITH_ALL_METRICS = build_pb2.Build(
    id=123,
    status=common_pb2.SUCCESS,
    output=BUILD_OUTPUT_WITH_ALL_METRICS,
    input=BUILD_INPUT,
)


def RunSteps(api):
  builds = [
      api.test_util.test_api.test_child_build(
          builder='eve-kernelnext-postsubmit',
          build_target_name='eve-kernelnext', critical='YES', status='SUCCESS',
          tags=api.cros_tags.tags(**{
              'relevance': 'relevant',
          })).message,
      api.test_util.test_api.test_child_build(
          builder='eve-postsubmit', build_target_name='eve', critical='YES',
          status='SUCCESS', tags=api.cros_tags.tags(**{
              'relevance': 'not relevant',
          })).message
  ]
  api.greenness.update_build_info(builds)

  api.greenness.update_irrelevant_scores()
  api.greenness.print_step()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(**{
          '$chromeos/greenness': {
              'publish_property': True
          },
      }),
      api.buildbucket.simulated_search_results(
          builds=[LAST_SNAPSHOT_WITH_BUILD_METRIC],
          step_name='getting last snapshot greenness.buildbucket.search'),
      api.step_data('getting last snapshot greenness.last snapshot.git log',
                    api.raw_io.stream_output_text('ababab\n')),
      api.buildbucket.simulated_search_results(
          builds=[LAST_SNAPSHOT_WITH_ALL_METRICS],
          step_name='propagate greenness scores.getting last snapshot greenness.buildbucket.search'
      ),
      api.step_data(
          'propagate greenness scores.getting last snapshot greenness.last snapshot.git log',
          api.raw_io.stream_output_text('ababab\n')),
      api.post_process(
          post_process.PropertyEquals, 'greenness', {
              'aggregateBuildMetric':
                  '99',
              'aggregateMetric':
                  '89',
              'builderGreenness': [{
                  'buildMetric': '100',
                  'builder': 'eve-kernelnext-postsubmit',
                  'metric': '100'
              }, {
                  'buildMetric': '98',
                  'builder': 'eve-postsubmit',
                  'context': 'IRRELEVANT',
                  'metric': '78'
              }]
          }))
