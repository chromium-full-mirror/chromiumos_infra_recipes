# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2, common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_tags',
    'greenness',
    'test_util',
]


# Test data.
BUILD_INPUT = build_pb2.Build.Input()
BUILD_INPUT.gitiles_commit.id = 'ababab'
BUILD_OUTPUT = build_pb2.Build.Output()
BUILD_OUTPUT.properties['greenness'] = {
    'aggregateMetric':
        98,
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
LAST_SNAPSHOT = build_pb2.Build(id=123, status=common_pb2.SUCCESS,
                                output=BUILD_OUTPUT, input=BUILD_INPUT)


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
  api.assertions.assertEqual(
      api.greenness.builder_greenness_dict['eve-kernelnext-postsubmit'].score,
      100)
  if api.properties['propagated_irrelevant_scores']:
    api.assertions.assertEqual(
        api.greenness.builder_greenness_dict['eve-postsubmit'].build_score, 98)
  api.greenness.print_step()
  api.assertions.assertEqual(
      api.greenness.get_greenness('eve-kernelnext').build_score, 100)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(**{'$chromeos/greenness': {
          'publish_property': True
      }}, propagated_irrelevant_scores=False))

  yield api.test(
      'with-last-greenness',
      api.properties(**{'$chromeos/greenness': {
          'publish_property': True
      }}, propagated_irrelevant_scores=True),
      api.buildbucket.simulated_search_results(
          builds=[LAST_SNAPSHOT],
          step_name='getting last snapshot greenness.buildbucket.search'),
      api.step_data('getting last snapshot greenness.last snapshot.git log',
                    api.raw_io.stream_output_text('ababab\n')),
  )
