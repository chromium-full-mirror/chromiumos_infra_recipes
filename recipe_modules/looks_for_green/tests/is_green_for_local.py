# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.looks_for_green.tests.test import \
  IsGreenForLocalProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'looks_for_green',
]

PROPERTIES = IsGreenForLocalProperties


# Mock build input values.
build_input = build_pb2.Build.Input()
build_input.gitiles_commit.id = 'test-commit-id'
build_input.gitiles_commit.host = 'test-host'
build_input.gitiles_commit.project = 'test-project'

# Mock child builds for the current snapshot.
current_snapshot_builds = [
    build_pb2.Build(
        id=123, builder=builder_common_pb2.BuilderID(builder='eve-snapshot'),
        tags=[common_pb2.StringPair(key='relevance', value='relevant')],
        input=build_input, status='SUCCESS', critical=common_pb2.YES),
    build_pb2.Build(
        id=234,
        builder=builder_common_pb2.BuilderID(builder='amd64-generic-snapshot'),
        tags=[common_pb2.StringPair(key='relevance', value='not relevant')],
        input=build_input, status='SUCCESS', critical=common_pb2.YES),
]

# Mock the previous snapshot build.
previous_snapshot = [
    build_pb2.Build(
        id=456567,
        builder=builder_common_pb2.BuilderID(builder='snapshot-orchestrator'))
]

# Mock the previous snapshot child builds.
previous_snapshot_builds_success = [
    build_pb2.Build(
        id=456,
        builder=builder_common_pb2.BuilderID(builder='amd64-generic-snapshot'),
        tags=[common_pb2.StringPair(key='relevance', value='relevant')],
        input=build_input, status='SUCCESS', critical=common_pb2.YES),
]
previous_snapshot_builds_failure = [
    build_pb2.Build(
        id=567,
        builder=builder_common_pb2.BuilderID(builder='amd64-generic-snapshot'),
        tags=[common_pb2.StringPair(key='relevance', value='relevant')],
        input=build_input, status='FAILURE', critical=common_pb2.YES),
]


def RunSteps(api, properties):
  is_green = api.looks_for_green.is_green_for_local()
  api.assertions.assertEqual(properties.expected_result, is_green)


def GenTests(api):
  yield api.test(
      'is-green-for-local',
      api.properties(expected_result=True),
      api.buildbucket.simulated_search_results(
          builds=current_snapshot_builds,
          step_name='check current snapshot build.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=previous_snapshot,
          step_name='get previous snapshot builds.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=previous_snapshot_builds_success,
          step_name='update with previous snapshot builds.buildbucket.search'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'is-not-green-for-local',
      api.properties(expected_result=False),
      api.buildbucket.simulated_search_results(
          builds=current_snapshot_builds,
          step_name='check current snapshot build.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=previous_snapshot,
          step_name='get previous snapshot builds.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=previous_snapshot_builds_failure,
          step_name='update with previous snapshot builds.buildbucket.search'),
      api.post_process(post_process.DropExpectation),
  )
