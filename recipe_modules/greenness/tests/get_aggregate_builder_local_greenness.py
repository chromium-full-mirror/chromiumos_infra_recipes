# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the get_aggregate_builder_local_greenness function."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'greenness',
    'test_util',
]



def RunSteps(api):
  agg_greenness = api.greenness.get_aggregate_builder_local_greenness(
      snapshot_commit='1234',
      snapshot_builder_names=api.properties['snapshot_builder_names'])

  api.assertions.assertEqual(agg_greenness,
                             api.properties['expected_agg_greenness'])


def GenTests(api):

  _bb_search_step_data = api.buildbucket.simulated_search_results([
      api.test_util.test_orchestrator(
          builder='snapshot-orchestrator', output_properties={
              'local_greenness': {
                  'greenness': {
                      'builder1-snapshot': [100, 100, True, True],
                      'builder2-snapshot': [0, 0, True, True],
                      'builder3-snapshot': [50, 50, True, True],
                  }
              }
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
          'greenness score: 0. Unable to find local greenness for 1 target(s)',
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
