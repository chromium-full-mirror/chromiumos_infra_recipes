# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from RECIPE_MODULES.chromeos.looks_for_green.test_utils import LooksStatusEquals
from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStatus
from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/time',
    'looks_for_green',
]

PROPERTIES = {
    'expect_result': Property(default=True),
    'expected_bbid': Property(default=0),
    'expected_greenness': Property(default=100),
    'expected_commit_sha': Property(default='abaaaa')
}

PYTHON_VERSION_COMPATIBILITY = 'PY3'

# Default values used in testing
TEST_SEED_TIME_SECONDS = 1613779827
TEST_START_TIMESTAMP = timestamp_pb2.Timestamp(seconds=1613754627)
TEST_START_TIMESTAMP2 = timestamp_pb2.Timestamp(seconds=1613754629)
TEST_END_TIMESTAMP = timestamp_pb2.Timestamp(seconds=1613779227)

# Mock builds
output = build_pb2.Build.Output()
output.properties['greenness'] = {'aggregateMetric': 80}
build_input = build_pb2.Build.Input()
build_input.gitiles_commit.id = 'ababab'
green_build = build_pb2.Build(id=123, output=output, input=build_input,
                              start_time=TEST_START_TIMESTAMP,
                              end_time=TEST_END_TIMESTAMP)

output = build_pb2.Build.Output()
output.properties['greenness'] = {'aggregateMetric': 98}
build_input.gitiles_commit.id = 'sample'
green_build2 = build_pb2.Build(id=234, output=output, input=build_input,
                               start_time=TEST_START_TIMESTAMP2,
                               end_time=TEST_END_TIMESTAMP)

output.properties['greenness'] = {'aggregateMetric': 60}
red_build = build_pb2.Build(id=123, output=output, input=build_input,
                            start_time=TEST_START_TIMESTAMP,
                            end_time=TEST_END_TIMESTAMP)


def RunSteps(api, expect_result, expected_bbid, expected_greenness,
             expected_commit_sha):
  snapshot = api.looks_for_green.find_green_snapshot()
  if expect_result:
    api.assertions.assertEqual(expected_bbid, snapshot.bbid)
    api.assertions.assertEqual(expected_greenness, snapshot.agg_green)
    api.assertions.assertEqual(expected_commit_sha, snapshot.commit_sha)
  else:
    api.assertions.assertEqual(None, snapshot)


def GenTests(api):
  yield api.test(
      'success',
      api.properties(expected_bbid=123, expected_greenness=80,
                     expected_commit_sha='ababab'),
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
              "-predicate",
              "{\"builder\": {\"bucket\": \"postsubmit\", \"builder\": \"snapshot-orchestrator\", \"project\": \"chromeos\"}, \"createTime\": {\"startTime\": \"2018-05-25T13:50:17Z\"}, \"status\": \"ENDED_MASK\"}"
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-greens',
      api.properties(expect_result=False),
      api.buildbucket.simulated_search_results(
          builds=[red_build],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_FOUND_NONE),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'latest-green',
      api.properties(expected_bbid=234, expected_greenness=98,
                     expected_commit_sha='sample'),
      api.time.seed(TEST_SEED_TIME_SECONDS),
      api.buildbucket.simulated_search_results(
          builds=[green_build, green_build2],
          step_name='find green snapshot.buildbucket.search'),
      api.post_check(LooksStatusEquals, LooksForGreenStatus.STATUS_RAN_OLDER),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging',
      api.properties(expected_bbid=123, expected_greenness=80,
                     expected_commit_sha='ababab'),
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
              "-predicate",
              "{\"builder\": {\"bucket\": \"staging\", \"builder\": \"staging-snapshot-orchestrator\", \"project\": \"chromeos\"}, \"createTime\": {\"startTime\": \"2018-05-25T13:50:17Z\"}, \"status\": \"ENDED_MASK\"}"
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
