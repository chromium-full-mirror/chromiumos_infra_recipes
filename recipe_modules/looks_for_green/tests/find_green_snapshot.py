# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import timestamp_pb2

from PB.chromiumos import greenness as greenness_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import \
  LooksForGreenStatus
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
]

PROPERTIES = FindGreenSnapshotProperties


# Default values used in testing
TEST_SEED_TIME_SECONDS = 1613779827
TEST_START_TIMESTAMP = timestamp_pb2.Timestamp(seconds=1613754627)
TEST_START_TIMESTAMP2 = timestamp_pb2.Timestamp(seconds=1613754629)
TEST_END_TIMESTAMP = timestamp_pb2.Timestamp(seconds=1613779227)

# Mock builds
output = build_pb2.Build.Output()
brya_greenness = {
    'buildMetric': '100',
    'metric': '98',
    'builder': 'brya-snapshot'
}
eve_greenness = {'buildMetric': '90', 'metric': '80', 'builder': 'eve-snapshot'}
output.properties['greenness'] = {
    'aggregateBuildMetric': 80,
    'builderGreenness': [brya_greenness]
}
build_input = build_pb2.Build.Input()
build_input.gitiles_commit.id = 'ababab'
green_build = build_pb2.Build(id=123, output=output, input=build_input,
                              start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP)

output = build_pb2.Build.Output()
output.properties['greenness'] = {
    'aggregateBuildMetric': 98,
    'builderGreenness': [brya_greenness, eve_greenness]
}
build_input.gitiles_commit.id = 'sample'
green_build2 = build_pb2.Build(id=234, output=output, input=build_input,
                               start_time=TEST_START_TIMESTAMP2,
                               end_time=TEST_END_TIMESTAMP)

output.properties['greenness'] = {
    'aggregateBuildMetric': 100,
    'builderGreenness': [brya_greenness]
}
greenest_build = build_pb2.Build(id=489, output=output, input=build_input,
                                 start_time=TEST_START_TIMESTAMP,
                                 end_time=TEST_END_TIMESTAMP)

output.properties['greenness'] = {'aggregateBuildMetric': 60}
red_build = build_pb2.Build(id=123, output=output, input=build_input,
                            start_time=TEST_START_TIMESTAMP,
                            end_time=TEST_END_TIMESTAMP)

unscored_build = build_pb2.Build(id=123, input=build_input,
                                 start_time=TEST_START_TIMESTAMP,
                                 end_time=TEST_END_TIMESTAMP)


expected_brya_greenness = {
    'brya-snapshot':
        greenness_pb2.AggregateGreenness.Greenness(build_metric=100, metric=98,
                                                   builder='brya-snapshot')
}
expected_both_greenness = {
    'eve-snapshot':
        greenness_pb2.AggregateGreenness.Greenness(build_metric=90, metric=80,
                                                   builder='eve-snapshot')
}
expected_both_greenness.update(expected_brya_greenness)

model_to_greenness = {
    'brya': expected_brya_greenness,
    'both': expected_both_greenness,
    '': {}
}


def RunSteps(api, properties):
  expected_builder_greenness = model_to_greenness.get(
      properties.expected_builder_greenness)
  expected_greenness = properties.expected_greenness or 100
  expected_commit_sha = properties.expected_commit_sha or 'abaaaa'
  latest_start = properties.latest_start

  # Parse timestamp proto, if provided.
  if latest_start:
    latest_start_ts = timestamp_pb2.Timestamp()
    latest_start_ts.FromJsonString(properties.latest_start)
    latest_start = latest_start_ts
  snapshot = api.looks_for_green.find_green_snapshot(latest_start=latest_start)
  if properties.expect_result:
    api.assertions.assertEqual(properties.expected_bbid, snapshot.bbid)
    api.assertions.assertEqual(expected_greenness, snapshot.agg_green)
    api.assertions.assertEqual(expected_commit_sha, snapshot.commit_sha)
    api.assertions.assertDictEqual(expected_builder_greenness,
                                   snapshot.builder_greenness)
  else:
    api.assertions.assertEqual(None, snapshot)


def GenTests(api):
  yield api.test(
      'success',
      api.properties(expect_result=True, expected_bbid=123,
                     expected_greenness=80, expected_commit_sha='ababab',
                     expected_builder_greenness='brya'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          builds=[green_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(
          post_process.StepCommandContains,
          'find green snapshot.buildbucket.search',
          [
              '-predicate',
              '{"builder": {"bucket": "postsubmit", "builder": "snapshot-orchestrator", "project": "chromeos"}, "createTime": {"startTime": "2021-02-19T14:10:28Z"}}'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-greens',
      api.properties(expect_result=False),
      api.buildbucket.simulated_search_results(
          builds=[red_build, unscored_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_FOUND_NONE),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'latest-green',
      api.properties(expect_result=True, expected_bbid=234,
                     expected_greenness=98, expected_commit_sha='sample',
                     expected_builder_greenness='both'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.simulated_search_results(
          builds=[green_build, green_build2],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'greenest',
      api.properties(expect_result=True, expected_bbid=489,
                     expected_greenness=100, expected_commit_sha='sample',
                     expected_builder_greenness='brya'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.simulated_search_results(
          builds=[green_build, green_build2, greenest_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging',
      api.properties(expect_result=True, expected_bbid=123,
                     expected_greenness=80, expected_commit_sha='ababab',
                     expected_builder_greenness='brya'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.ci_build(project='chromeos', bucket='staging',
                               builder='staging-cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          builds=[green_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(
          post_process.StepCommandContains,
          'find green snapshot.buildbucket.search',
          [
              '-predicate',
              '{"builder": {"bucket": "staging", "builder": "staging-snapshot-orchestrator", "project": "chromeos"}, "createTime": {"startTime": "2021-02-19T14:10:28Z"}}'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'latest-time',
      api.properties(expect_result=True, expected_bbid=123,
                     expected_greenness=80, expected_commit_sha='ababab',
                     latest_start=timestamp_pb2.Timestamp(seconds=1613779200),
                     expected_builder_greenness='brya'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          builds=[green_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_process(
          post_process.StepCommandContains,
          'find green snapshot.buildbucket.search',
          [
              '-predicate',
              '{"builder": {"bucket": "postsubmit", "builder": "snapshot-orchestrator", "project": "chromeos"}, "createTime": {"endTime": "2021-02-20T00:00:00Z", "startTime": "2021-02-19T14:00:00Z"}}'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
