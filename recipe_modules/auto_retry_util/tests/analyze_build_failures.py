# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs
from PB.chromiumos import greenness as greenness_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES
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
  success, retryable, outstanding = api.auto_retry_util.analyze_build_failures(
      api.buildbucket.build)
  api.auto_retry_util.publish_per_build_stats()
  expected_success = api.properties['expected_success']
  expected_retryable = api.properties['expected_retryable']
  expected_outstanding = api.properties['expected_outstanding']
  api.assertions.assertCountEqual(success, expected_success)
  api.assertions.assertCountEqual(retryable, expected_retryable)
  api.assertions.assertCountEqual(outstanding, expected_outstanding)


def GenTests(api):

  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'cq-orchestrator'
  orch.orchestrator.child_specs.add().name = 'builder1-cq'
  orch.orchestrator.child_specs.add().name = 'builder2-cq'
  orch.orchestrator.child_specs.add().name = 'builder4-cq'
  orch.orchestrator.child_specs.add().name = 'builder5-cq'
  orch.orchestrator.child_specs.add().name = 'builder6-cq'
  orch.orchestrator.child_specs.add().name = 'builder7-kernelnext-cq'
  orch.orchestrator.child_specs.add().name = 'non-critical-builder-cq'
  builder2 = configs.builder_configs.add()
  builder2.id.name = 'builder2-cq'
  builder5 = configs.builder_configs.add()
  builder5.id.name = 'builder5-cq'
  builder6 = configs.builder_configs.add()
  builder6.id.name = 'builder6-slim-cq'
  builder7 = configs.builder_configs.add()
  builder7.id.name = 'builder7-kernelnext-cq'

  child_build_info = [
      {
          'builder': {
              'builder': 'builder1-cq'
          },
          'status': 'SUCCESS',
          'relevant': True,
          'collect_value': 'COLLECT',
      },
      {
          'builder': {
              'builder': 'builder2-cq'
          },
          'status': 'FAILURE',
          'relevant': True,
          'collect_value': 'COLLECT_AFTER_HW_TEST',
      },
      {
          'builder': {
              'builder': 'builder3-cq'
          },
          'status': 'FAILURE',
          'relevant': True,
          'collect_value': 'COLLECT',
      },
      {
          'builder': {
              'builder': 'builder4-cq'
          },
          'status': 'SUCCESS',
          'relevant': False,
          'collect_value': 'COLLECT_AFTER_HW_TEST',
      },
      {
          'builder': {
              'builder': 'builder5-cq'
          },
          'status': 'INFRA_FAILURE',
          'relevant': True,
          'collect_value': 'COLLECT_AFTER_HW_TEST',
      },
      {
          'builder': {
              'builder': 'builder6-slim-cq'
          },
          'status': 'FAILURE',
          'relevant': True,
          'collect_value': 'COLLECT',
      },
      {
          'builder': {
              'builder': 'builder7-kernelnext-cq'
          },
          'status': 'FAILURE',
          'relevant': True,
          'collect_value': 'COLLECT',
      },
      {
          'builder': {
              'builder': 'non-critical-builder-cq'
          },
          'status': 'FAILURE',
          'relevant': True,
          'collect_value': 'NO_COLLECT',
      },
  ]
  yield api.test(
      'removed-verifier',
      api.test_util.test_orchestrator(output_properties={
          'child_build_info': child_build_info
      }).build,
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          expected_success=['builder1-cq', 'builder4-cq'],
          expected_retryable=['builder3-cq'],
          expected_outstanding=[
              'builder2-cq', 'builder5-cq', 'builder6-slim-cq',
              'builder7-kernelnext-cq'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'infra-failure-experiment-feature-retryable-flake',
      api.test_util.test_orchestrator(output_properties={
          'child_build_info': child_build_info
      }).build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES)
                  ])
          }),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          expected_success=['builder1-cq', 'builder4-cq'],
          expected_retryable=['builder3-cq', 'builder5-cq'],
          expected_outstanding=[
              'builder2-cq', 'builder6-slim-cq', 'builder7-kernelnext-cq'
          ]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'infra-failure-experiment-feature-not-retryable',
      api.test_util.test_orchestrator(
          output_properties={
              'child_build_info': [{
                  'builder': {
                      'builder': 'builder1-cq'
                  },
                  'status': 'INFRA_FAILURE',
                  'relevant': True,
                  'collect_value': 'COLLECT',
              },],
          }).build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES)
                  ])
          }),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(expected_success=[], expected_retryable=[],
                     expected_outstanding=['builder1-cq']),
      api.post_process(post_process.DropExpectation),
  )

  FAILED_SNAPSHOT_OUTPUT_PROPERTIES = build_pb2.Build.Output()
  FAILED_SNAPSHOT_OUTPUT_PROPERTIES.properties[
      'greenness'] = json_format.MessageToDict(
          greenness_pb2.AggregateGreenness(
              aggregate_build_metric=75, aggregate_metric=75,
              builder_greenness=[
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder2-snapshot',
                      metric=0,
                      build_metric=0,
                  ),
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder3-snapshot',
                      metric=100,
                      build_metric=100,
                  ),
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder5-snapshot',
                      metric=100,
                      build_metric=100,
                  ),
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder6-snapshot',
                      metric=100,
                      build_metric=100,
                  ),
              ]))

  GREEN_SNAPSHOT_OUTPUT_PROPERTIES = build_pb2.Build.Output()
  GREEN_SNAPSHOT_OUTPUT_PROPERTIES.properties[
      'greenness'] = json_format.MessageToDict(
          greenness_pb2.AggregateGreenness(
              aggregate_build_metric=100, aggregate_metric=100,
              builder_greenness=[
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
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder5-snapshot',
                      metric=100,
                      build_metric=100,
                  ),
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder6-snapshot',
                      metric=100,
                      build_metric=100,
                  ),
              ]))

  yield api.test(
      'wait-for-green-experiment-feature',
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN)
                  ])
          }),
      api.test_util.test_orchestrator(
          output_properties={
              'child_build_info': child_build_info,
              'looks_for_green': {
                  'status': 'STATUS_FOUND_NONE',
              },
          },
          output_gitiles_commit=common_pb2.GitilesCommit(
              host='chrome-internal.googlesource.com',
              project='chromeos/manifest-internal',
              id='abc',
              ref='refs/heads/snapshot',
          ),
      ).build,
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              builder=builder_common_pb2.BuilderID(
                  project='chromeos',
                  bucket='postsubmit',
                  builder='snapshot-orchestrator',
              ),
              output=FAILED_SNAPSHOT_OUTPUT_PROPERTIES,
          ),
      ], 'analyzing build results.get now green builders.get greenness for commit abc.buildbucket.search'
                                              ),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(
                  builder=builder_common_pb2.BuilderID(
                      project='chromeos',
                      bucket='postsubmit',
                      builder='snapshot-orchestrator',
                  ),
                  output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
              ),
          ],
          step_name='analyzing build results.determine CQ retry snapshot.find green snapshot.buildbucket.search'
      ),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          expected_success=['builder1-cq', 'builder4-cq'], expected_retryable=[
              'builder2-cq', 'builder3-cq', 'builder7-kernelnext-cq'
          ], expected_outstanding=['builder5-cq', 'builder6-slim-cq']),
      api.post_process(post_process.PropertyEquals, 'per_build_stats', [{
          'build_id': '8945511751514863184',
          'outstanding_builders': ['builder5-cq', 'builder6-slim-cq'],
          'outstanding_test_suites': [],
          'retryable_builders':
              ['builder2-cq', 'builder3-cq', 'builder7-kernelnext-cq'],
          'retryable_test_suites': [],
          'wait_for_green_stats': {
              'failed_builders_in_snapshot': ['builder2-snapshot'],
              'no_snapshot_data_retryable_builders': ['builder7-kernelnext-cq'],
              'now_green_builders': ['builder2-snapshot'],
              'retryable_builders': ['builder2-cq'],
              'total_builders_in_snapshot': 4
          },
          'filter_reasons': [],
      }]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'wait-for-green-experiment-feature-no-green-snapshot-found',
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN)
                  ])
          }),
      api.test_util.test_orchestrator(
          output_properties={
              'child_build_info': child_build_info,
              'looks_for_green': {
                  'status': 'STATUS_FOUND_NONE',
              },
          },
          output_gitiles_commit=common_pb2.GitilesCommit(
              host='chrome-internal.googlesource.com',
              project='chromeos/manifest-internal',
              id='abc',
              ref='refs/heads/snapshot',
          ),
      ).build,
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              builder=builder_common_pb2.BuilderID(
                  project='chromeos',
                  bucket='postsubmit',
                  builder='snapshot-orchestrator',
              ),
              output=FAILED_SNAPSHOT_OUTPUT_PROPERTIES,
          ),
      ], 'analyzing build results.determine CQ retry snapshot.find green snapshot.buildbucket.search'
                                              ),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          expected_success=['builder1-cq', 'builder4-cq'],
          expected_retryable=['builder3-cq'], expected_outstanding=[
              'builder2-cq', 'builder5-cq', 'builder6-slim-cq',
              'builder7-kernelnext-cq'
          ]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'wait-for-green-experiment-lfg-stats-missing',
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN)
                  ])
          }),
      api.test_util.test_orchestrator(
          output_properties={
              'child_build_info': child_build_info,
          },
          output_gitiles_commit=common_pb2.GitilesCommit(
              host='chrome-internal.googlesource.com',
              project='chromeos/manifest-internal',
              id='abc',
              ref='refs/heads/snapshot',
          ),
      ).build,
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              builder=builder_common_pb2.BuilderID(
                  project='chromeos',
                  bucket='postsubmit',
                  builder='snapshot-orchestrator',
              ),
              output=FAILED_SNAPSHOT_OUTPUT_PROPERTIES,
          ),
      ], 'analyzing build results.get now green builders.get greenness for commit abc.buildbucket.search'
                                              ),
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
      api.properties(
          expected_success=['builder1-cq', 'builder4-cq'], expected_retryable=[
              'builder2-cq', 'builder3-cq', 'builder7-kernelnext-cq'
          ], expected_outstanding=['builder5-cq', 'builder6-slim-cq']),
      api.post_process(post_process.StepTextContains,
                       'analyzing build results.determine CQ retry snapshot',
                       ['build skipped LFG, using latest scored snapshot']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'wait-for-green-experiment-lfg-status-skipped',
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN)
                  ])
          }),
      api.test_util.test_orchestrator(
          output_properties={
              'child_build_info': child_build_info,
              'looks_for_green': {
                  'status': 'STATUS_SKIPPED_CQ_DEPEND'
              },
          },
          output_gitiles_commit=common_pb2.GitilesCommit(
              host='chrome-internal.googlesource.com',
              project='chromeos/manifest-internal',
              id='abc',
              ref='refs/heads/snapshot',
          ),
      ).build,
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              builder=builder_common_pb2.BuilderID(
                  project='chromeos',
                  bucket='postsubmit',
                  builder='snapshot-orchestrator',
              ),
              output=FAILED_SNAPSHOT_OUTPUT_PROPERTIES,
          ),
      ], 'analyzing build results.get now green builders.get greenness for commit abc.buildbucket.search'
                                              ),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(
                  builder=builder_common_pb2.BuilderID(
                      project='chromeos',
                      bucket='postsubmit',
                      builder='snapshot-orchestrator',
                  ),
                  output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
              ),
          ],
          step_name='analyzing build results.determine CQ retry snapshot.checking latest scored snapshot greenness.buildbucket.search'
      ),
      api.properties(
          expected_success=['builder1-cq', 'builder4-cq'], expected_retryable=[
              'builder2-cq', 'builder3-cq', 'builder7-kernelnext-cq'
          ], expected_outstanding=['builder5-cq', 'builder6-slim-cq']),
      api.post_process(post_process.StepTextContains,
                       'analyzing build results.determine CQ retry snapshot',
                       ['build skipped LFG, using latest scored snapshot']),
      api.post_process(post_process.DropExpectation),
  )
