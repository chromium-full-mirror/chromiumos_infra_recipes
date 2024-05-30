# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests caching greenness for the latest snapshot."""

from google.protobuf import json_format

from recipe_engine import post_process

from PB.chromiumos import greenness as greenness_pb2
from PB.chromiumos.builder_config import BuilderConfigs
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'auto_retry_util',
    'cros_infra_config',
    'test_util',
]



def RunSteps(api):
  child_build_info = [
      {
          'builder': {
              'builder': 'builder1-cq'
          },
          'status': 'FAILURE',
          'relevant': True,
          'collect_value': 'COLLECT',
      },
  ]

  # Create 3 candidate builds, the first two used snapshot abc, the second two
  # used snapshot def.
  candidates = []
  for i in range(3):
    candidate = build_pb2.Build()
    candidate.output.properties['child_build_info'] = child_build_info
    candidate.output.properties['looks_for_green'] = {
        'status': 'STATUS_SKIPPED_CQ_DEPEND'
    }
    candidate.output.gitiles_commit.id = 'abc' if i < 2 else 'def'
    candidates.append(candidate)

  for b in candidates:
    api.auto_retry_util.analyze_build_failures(b)


def GenTests(api):

  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'cq-orchestrator'
  orch.orchestrator.child_specs.add().name = 'builder1-cq'

  GREEN_SNAPSHOT_OUTPUT_PROPERTIES = build_pb2.Build.Output()
  GREEN_SNAPSHOT_OUTPUT_PROPERTIES.properties[
      'greenness'] = json_format.MessageToDict(
          greenness_pb2.AggregateGreenness(
              aggregate_build_metric=100, aggregate_metric=100,
              builder_greenness=[
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder1-snapshot',
                      metric=100,
                      build_metric=100,
                  ),
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder2-snapshot',
                      metric=100,
                      build_metric=100,
                  ),
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder3-snapshot',
                      metric=100,
                      build_metric=100,
                  ),
              ]))

  yield api.test(
      'cache-used',
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN)
                  ])
          }),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(
                  builder=builder_common_pb2.BuilderID(
                      project='chromeos',
                      bucket='postsubmit',
                      builder='snapshot-orchestrator',
                  ),
                  output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
                  input=build_pb2.Build.Input(
                      gitiles_commit=common_pb2.GitilesCommit(id='abc'),
                  ),
              ),
          ],
          step_name='analyzing build results.determine CQ retry snapshot.checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.post_process(
          post_process.MustRun,
          'analyzing build results.determine CQ retry snapshot.checking latest scored snapshot greenness.buildbucket.search',
      ),
      # Don't search for snapshot abc again.
      api.post_process(
          post_process.DoesNotRun,
          'analyzing build results (2).determine CQ retry snapshot.checking latest scored snapshot greenness.buildbucket.search',
      ),
      # Also don't search for snapshot def.
      api.post_process(
          post_process.DoesNotRun,
          'analyzing build results (3).determine CQ retry snapshot.checking latest scored snapshot greenness.buildbucket.search',
      ),
      api.post_process(post_process.DropExpectation),
  )
