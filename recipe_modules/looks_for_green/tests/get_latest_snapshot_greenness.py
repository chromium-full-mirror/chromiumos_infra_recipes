# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.looks_for_green.tests.test import \
  GetLatestSnapshotGreennessProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/time',
    'cros_infra_config',
    'looks_for_green',
]

PROPERTIES = GetLatestSnapshotGreennessProperties


# Default values used in testing
TEST_SEED_TIME_SECONDS = 1613779827
TEST_START_TIMESTAMP = timestamp_pb2.Timestamp(seconds=1613754627)
TEST_END_TIMESTAMP = timestamp_pb2.Timestamp(seconds=1613779227)


def RunSteps(api, properties):
  snapshot = api.looks_for_green.get_latest_snapshot_greenness()
  api.assertions.assertEqual(properties.expected_greenness,
                             snapshot.agg_green if snapshot else -1)
  api.assertions.assertEqual(properties.expected_staging,
                             api.cros_infra_config.is_staging)


def GenTests(api):
  output = build_pb2.Build.Output()
  output.properties['greenness'] = {'aggregateBuildMetric': 100}
  output.properties['commit'] = {'id': 'sampleSHA'}

  yield api.test(
      'success-but-scored',
      api.properties(
          **{'$chromeos/looks_for_green': {
              'use_scored_over_minted': True,
          }}, expected_greenness=100, expected_is_snap_orch_green=True),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(id=123, output=output,
                              start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP)
          ],
          step_name='checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging',
      api.properties(expected_greenness=100, expected_is_snap_orch_green=True,
                     expected_staging=True),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='staging',
          builder='staging-cq-orchestrator',
      ),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(id=123, output=output,
                              start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP)
          ],
          step_name='checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.post_process(post_process.DropExpectation),
  )

  output.properties['greenness'] = {'aggregateBuildMetric': 70}
  yield api.test(
      'greenness-below-threshold',
      api.properties(expected_greenness=70, expected_is_snap_orch_green=False),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(id=123, output=output,
                              start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP)
          ],
          step_name='checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.post_process(post_process.DropExpectation),
  )

  output.properties['greenness'] = {}
  yield api.test(
      'unset-greenness',
      api.properties(expected_greenness=-1, expected_is_snap_orch_green=False),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(id=123, output=output,
                              start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP),
              build_pb2.Build(id=123, output=output,
                              start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP)
          ],
          step_name='checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'unset-output-props',
      api.properties(expected_greenness=-1, expected_is_snap_orch_green=False),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(id=123, start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP),
              build_pb2.Build(id=123, start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP),
          ],
          step_name='checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-builds',
      api.properties(expected_greenness=-1, expected_is_snap_orch_green=False),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.simulated_search_results(
          builds=[],
          step_name='checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.post_process(post_process.DropExpectation),
  )

  output.properties['greenness'] = {'aggregateBuildMetric': 100}
  yield api.test(
      'no-greenness-on-latest-snaps',
      api.properties(expected_greenness=-1, expected_is_snap_orch_green=False),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(id=123, start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP),
              build_pb2.Build(id=123, start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP),
              build_pb2.Build(id=123, start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP),
          ],
          step_name='checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
