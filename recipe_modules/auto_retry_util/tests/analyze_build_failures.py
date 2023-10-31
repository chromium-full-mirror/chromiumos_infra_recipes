# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs
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

PYTHON_VERSION_COMPATIBILITY = 'PY3'


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

  child_build_info = [
      {
          'builder': {
              'builder': 'builder1-cq'
          },
          'status': 'SUCCESS',
          'relevant': True
      },
      {
          'builder': {
              'builder': 'builder2-cq'
          },
          'status': 'FAILURE',
          'relevant': True
      },
      {
          'builder': {
              'builder': 'builder3-cq'
          },
          'status': 'FAILURE',
          'relevant': True
      },
      {
          'builder': {
              'builder': 'builder4-cq'
          },
          'status': 'SUCCESS',
          'relevant': False
      },
      {
          'builder': {
              'builder': 'builder5-cq'
          },
          'status': 'INFRA_FAILURE',
          'relevant': True
      },
      {
          'builder': {
              'builder': 'builder6-slim-cq'
          },
          'status': 'FAILURE',
          'relevant': True
      },
      {
          'builder': {
              'builder': 'builder7-kernelnext-cq'
          },
          'status': 'FAILURE',
          'relevant': True
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
                  'relevant': True
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
  FAILED_SNAPSHOT_OUTPUT_PROPERTIES.properties['greenness'] = {
      'aggregateMetric': 75,
      'aggregateBuildMetric': 75,
  }
  FAILED_SNAPSHOT_OUTPUT_PROPERTIES.properties['local_greenness'] = {
      'greenness': {
          'builder2-snapshot': [0, 0, True, True],
          'builder3-snapshot': [100, 100, True, True],
          'builder5-snapshot': [100, 100, True, True],
          'builder6-snapshot': [100, 100, True, True],
      }
  }

  GREEN_SNAPSHOT_OUTPUT_PROPERTIES = build_pb2.Build.Output()
  GREEN_SNAPSHOT_OUTPUT_PROPERTIES.properties['greenness'] = {
      'aggregateMetric': 100,
      'aggregateBuildMetric': 100,
  }
  GREEN_SNAPSHOT_OUTPUT_PROPERTIES.properties['local_greenness'] = {
      'greenness': {
          'builder2-snapshot': [100, 100, True, True],
          'builder3-snapshot': [100, 100, True, True],
          'builder5-snapshot': [100, 100, True, True],
          'builder6-snapshot': [100, 100, True, True]
      }
  }

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
              'child_build_info': child_build_info
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
      ], 'analyzing build results.get now green builders.get tot failure builders.buildbucket.search'
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
          step_name='analyzing build results.get now green builders.find green snapshot.buildbucket.search'
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
          }
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
              'child_build_info': child_build_info
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
      ], 'analyzing build results.get now green builders.get tot failure builders.buildbucket.search'
                                              ),
      api.buildbucket.simulated_search_results(
          builds=[
              build_pb2.Build(
                  builder=builder_common_pb2.BuilderID(
                      project='chromeos',
                      bucket='postsubmit',
                      builder='snapshot-orchestrator',
                  ),
                  output=FAILED_SNAPSHOT_OUTPUT_PROPERTIES,
              ),
          ],
          step_name='analyzing build results.get now green builders.find green snapshot.buildbucket.search'
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
