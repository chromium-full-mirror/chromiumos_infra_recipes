# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the get_aggregate_builder_greenness function."""

from google.protobuf import json_format

from recipe_engine import post_process

from PB.chromiumos import greenness as greenness_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'greenness',
    'test_util',
]



def RunSteps(api):
  agg_greenness = api.greenness.get_aggregate_builder_greenness(
      snapshot_commit='1234',
      snapshot_builder_names=api.properties['snapshot_builder_names'])

  api.assertions.assertEqual(agg_greenness,
                             api.properties['expected_agg_greenness'])


def GenTests(api):

  _bb_search_step_data = api.buildbucket.simulated_search_results([
      api.test_util.test_orchestrator(
          builder='snapshot-orchestrator', output_properties={
              'greenness':
                  json_format.MessageToDict(
                      greenness_pb2.AggregateGreenness(builder_greenness=[
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='builder1-snapshot',
                              build_metric=100,
                              metric=100,
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='builder2-snapshot',
                              build_metric=0,
                              metric=0,
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              builder='builder3-snapshot',
                              build_metric=50,
                              metric=50,
                          ),
                      ]))
          }).message
  ], 'get greenness for specified builders.buildbucket.search')

  yield api.test(
      'basic',
      api.properties(
          snapshot_builder_names=[
              'builder1-snapshot',
              'builder2-snapshot',
              'builder3-snapshot',
          ], expected_agg_greenness=50),
      _bb_search_step_data,
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'missing-greenness-builder',
      api.properties(snapshot_builder_names=['fake-build'],
                     expected_agg_greenness=0),
      api.post_process(
          post_process.StepTextEquals,
          'get greenness for specified builders',
          'greenness score: 0. Unable to find greenness for 1 target(s)',
      ),
      _bb_search_step_data,
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'some-found-some-missing',
      api.properties(
          snapshot_builder_names=[
              'builder1-snapshot',
              'builder2-snapshot',
              'builder3-snapshot',
              'fake-build',
          ], expected_agg_greenness=37),
      _bb_search_step_data,
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-snapshot-orch-found',
      api.properties(snapshot_builder_names=['fake-build'],
                     expected_agg_greenness=0),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-builders-passed-in',
      api.properties(snapshot_builder_names=[]),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
