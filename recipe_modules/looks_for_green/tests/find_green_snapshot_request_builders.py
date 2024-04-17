# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for find_green_snapshot with requested builders."""

from google.protobuf import json_format

from PB.chromiumos import greenness as greenness_pb2
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import \
  LooksForGreenStatus
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import \
  LooksForGreenProperties
from PB.recipe_modules.chromeos.looks_for_green.tests.test import \
  FindGreenSnapshotProperties
from RECIPE_MODULES.chromeos.looks_for_green.test_utils import LooksStatusEquals
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/time',
    'looks_for_green',
    'test_util',
]

PROPERTIES = FindGreenSnapshotProperties


def RunSteps(api, properties):
  snapshot = api.looks_for_green.find_green_snapshot(
      requested_snapshot_builders=properties.requested_snapshot_builders)

  expected_bbid = properties.expected_bbid
  expected_commit_sha = properties.expected_commit_sha
  expected_green = properties.expected_greenness
  expected_requested_green = properties.expected_requested_builders_greenness
  expected_missing = properties.expected_requested_builders_missing_from_snapshot
  if not expected_missing and not properties.requested_snapshot_builders:
    expected_missing = None

  if not properties.expect_result:
    api.assertions.assertEqual(None, snapshot)
    assert not (expected_bbid or expected_commit_sha or expected_green or
                expected_requested_green or expected_missing
               ), 'These values are only valid if expected_result is True'

    return

  api.assertions.assertEqual(expected_bbid, snapshot.bbid)
  api.assertions.assertEqual(expected_commit_sha, snapshot.commit_sha)
  api.assertions.assertEqual(expected_green, snapshot.agg_green)
  api.assertions.assertEqual(expected_requested_green,
                             snapshot.requested_builders_agg_green)
  api.assertions.assertEqual(properties.requested_snapshot_builders,
                             snapshot.requested_builders)
  api.assertions.assertEqual(expected_missing,
                             snapshot.requested_builders_missing_from_snapshot)


def GenTests(api):

  # Default values used in testing
  TEST_SEED_TIME_SECONDS = 1613779827
  # Three hours before "current" time.
  TEST_START_SECONDS = TEST_SEED_TIME_SECONDS - (60 * 60 * 3)

  snapshot_build = api.test_util.test_orchestrator(
      build_id=111, start_time=TEST_START_SECONDS, revision='aaaaaa',
      output_properties={
          'greenness':
              json_format.MessageToDict(
                  greenness_pb2.AggregateGreenness(
                      aggregate_build_metric=75, builder_greenness=[
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=100,
                              builder='target-1-snapshot',
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=100,
                              builder='target-2-snapshot',
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=100,
                              builder='target-3-snapshot',
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=0,
                              builder='target-4-snapshot',
                          ),
                      ]))
      }).message

  yield api.test(
      'red-snapshot-no-builders-requested-found-none',
      api.properties(expect_result=False),
      api.properties(
          **{
              '$chromeos/looks_for_green':
                  LooksForGreenProperties(greenness_threshold=80)
          }),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.try_build(project='chromeos', bucket='postsubmit',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          builds=[snapshot_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_FOUND_NONE),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'green-snapshot-no-builders-requested-found-green',
      api.properties(expect_result=True, expected_greenness=75,
                     expected_bbid=111, expected_commit_sha='aaaaaa',
                     expected_requested_builders_greenness=75,
                     expected_requested_builders_missing_from_snapshot=None),
      api.properties(
          **{
              '$chromeos/looks_for_green':
                  LooksForGreenProperties(greenness_threshold=50)
          }),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.try_build(project='chromeos', bucket='postsubmit',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          builds=[snapshot_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'red-snapshot-but-green-for-specified-builders-found-green',
      api.properties(
          expect_result=True, expected_bbid=111, expected_commit_sha='aaaaaa',
          expected_greenness=75, expected_requested_builders_greenness=100,
          requested_snapshot_builders=[
              'target-1-snapshot',
              'target-2-snapshot',
          ]),
      api.properties(
          **{
              '$chromeos/looks_for_green':
                  LooksForGreenProperties(greenness_threshold=80)
          }),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.try_build(project='chromeos', bucket='postsubmit',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          builds=[snapshot_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'snapshot-missing-greenness-for-some-specified-builders-found-green',
      api.properties(
          expect_result=True, expected_bbid=111, expected_commit_sha='aaaaaa',
          expected_greenness=75, expected_requested_builders_greenness=66,
          requested_snapshot_builders=[
              'target-1-snapshot',
              'target-2-snapshot',
              'non-existent-target-snapshot',
          ], expected_requested_builders_missing_from_snapshot=[
              'non-existent-target-snapshot'
          ]),
      api.properties(
          **{
              '$chromeos/looks_for_green':
                  LooksForGreenProperties(greenness_threshold=60)
          }),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.try_build(project='chromeos', bucket='postsubmit',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          builds=[snapshot_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(post_process.DropExpectation),
  )

  newer_snapshot_build = api.test_util.test_orchestrator(
      build_id=222, start_time=TEST_START_SECONDS + (60 * 60 * 1),
      revision='bbbbbb', output_properties={
          'greenness':
              json_format.MessageToDict(
                  greenness_pb2.AggregateGreenness(
                      aggregate_build_metric=50, builder_greenness=[
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=100,
                              builder='target-1-snapshot',
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=100,
                              builder='target-2-snapshot',
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=0,
                              builder='target-3-snapshot',
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=0,
                              builder='target-4-snapshot',
                          ),
                      ]))
      }).message

  yield api.test(
      'multiple-equally-green-takes-latest',
      api.properties(
          expect_result=True, expected_bbid=222, expected_commit_sha='bbbbbb',
          expected_greenness=50, expected_requested_builders_greenness=100,
          requested_snapshot_builders=[
              'target-1-snapshot',
              'target-2-snapshot',
          ]),
      api.properties(
          **{
              '$chromeos/looks_for_green':
                  LooksForGreenProperties(greenness_threshold=60)
          }),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.try_build(project='chromeos', bucket='postsubmit',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          builds=[snapshot_build, newer_snapshot_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(post_process.DropExpectation),
  )

  older_greener_snapshot_build = api.test_util.test_orchestrator(
      build_id=333, start_time=TEST_START_SECONDS - (60 * 60 * 1),
      revision='cccccc', output_properties={
          'greenness':
              json_format.MessageToDict(
                  greenness_pb2.AggregateGreenness(
                      aggregate_build_metric=75, builder_greenness=[
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=100,
                              builder='target-1-snapshot',
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=100,
                              builder='target-2-snapshot',
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=0,
                              builder='target-3-snapshot',
                          ),
                          greenness_pb2.AggregateGreenness.Greenness(
                              build_metric=100,
                              builder='target-4-snapshot',
                          ),
                      ]))
      }).message

  yield api.test(
      'multiple-green-takes-greenest',
      api.properties(
          expect_result=True, expected_bbid=333, expected_commit_sha='cccccc',
          expected_greenness=75, expected_requested_builders_greenness=100,
          requested_snapshot_builders=[
              'target-1-snapshot',
              'target-2-snapshot',
              'target-4-snapshot',
          ]),
      api.properties(
          **{
              '$chromeos/looks_for_green':
                  LooksForGreenProperties(greenness_threshold=60)
          }),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.try_build(project='chromeos', bucket='postsubmit',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          builds=[
              snapshot_build, newer_snapshot_build, older_greener_snapshot_build
          ], step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(post_process.DropExpectation),
  )
