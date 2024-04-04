# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests retrying package failures unrelated to the changes under test."""

from google.protobuf import json_format

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs
from PB.chromiumos import greenness as greenness_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'auto_retry_util',
    'cros_infra_config',
    'test_util',
]


def RunSteps(api):
  _, retryable, outstanding = api.auto_retry_util.analyze_build_failures(
      api.buildbucket.build)
  expected_retryable = api.properties['expected_retryable']
  expected_outstanding = api.properties['expected_outstanding']
  api.assertions.assertCountEqual(retryable, expected_retryable)
  api.assertions.assertCountEqual(outstanding, expected_outstanding)


def GenTests(api):

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
                  )
              ]))

  child_build_info = [
      {
          'builder': {
              'builder': 'builder1-cq'
          },
          'status': 'FAILURE',
          'relevant': True,
          'collect_value': 'COLLECT',
          'package_failures': [{
              'affectedByChanges': False
          }]
      },
  ]

  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'cq-orchestrator'
  orch.orchestrator.child_specs.add().name = 'builder1-cq'
  yield api.test(
      'unrelated-package-failure',
      api.test_util.test_orchestrator(output_properties={
          'child_build_info': child_build_info
      }).build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES
                      )
                  ])
          }),
      api.buildbucket.simulated_search_results([
          build_pb2.Build(
              builder=builder_common_pb2.BuilderID(
                  project='chromeos',
                  bucket='postsubmit',
                  builder='snapshot-orchestrator',
              ),
              output=GREEN_SNAPSHOT_OUTPUT_PROPERTIES,
          ),
      ], 'analyzing build results.get tot failure builders.buildbucket.search'),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(expected_retryable=['builder1-cq'],
                     expected_outstanding=[]),
      api.post_process(post_process.DropExpectation),
  )

  at_fault_child_build_info = [
      {
          'builder': {
              'builder': 'builder1-cq'
          },
          'status': 'FAILURE',
          'relevant': True,
          'collect_value': 'COLLECT',
          'package_failures': [{
              'affectedByChanges': True
          }]
      },
  ]

  yield api.test(
      'at-fault-package-failure',
      api.test_util.test_orchestrator(output_properties={
          'child_build_info': at_fault_child_build_info
      }).build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES
                      )
                  ])
          }),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(expected_retryable=[],
                     expected_outstanding=['builder1-cq']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-child-build-info',
      api.test_util.test_orchestrator().build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES
                      )
                  ])
          }),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(expected_retryable=[], expected_outstanding=[]),
      api.post_process(post_process.DropExpectation),
  )

  no_pkg_failure_child_build_info = [
      {
          'builder': {
              'builder': 'builder1-cq'
          },
          'status': 'FAILURE',
          'relevant': True,
          'collect_value': 'COLLECT',
      },
  ]
  yield api.test(
      'not-a-package-failure',
      api.test_util.test_orchestrator(output_properties={
          'child_build_info': no_pkg_failure_child_build_info
      }).build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES
                      )
                  ])
          }),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(expected_retryable=[],
                     expected_outstanding=['builder1-cq']),
      api.post_process(post_process.DropExpectation),
  )

  removed_verifier_configs = BuilderConfigs()
  removed_verifier_orch = removed_verifier_configs.builder_configs.add()
  removed_verifier_orch.id.name = 'cq-orchestrator'
  yield api.test(
      'unrelated-package-failure-but-already-retriable',
      api.test_util.test_orchestrator(output_properties={
          'child_build_info': child_build_info
      }).build,
      api.cros_infra_config.override_builder_configs_test_data(
          removed_verifier_configs),
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES
                      )
                  ])
          }),
      api.cros_infra_config.override_builder_configs_test_data(
          removed_verifier_configs),
      api.properties(expected_retryable=['builder1-cq'],
                     expected_outstanding=[]),
      api.post_process(post_process.DropExpectation),
  )

  FAILED_SNAPSHOT_OUTPUT_PROPERTIES = build_pb2.Build.Output()
  FAILED_SNAPSHOT_OUTPUT_PROPERTIES.properties[
      'greenness'] = json_format.MessageToDict(
          greenness_pb2.AggregateGreenness(
              aggregate_build_metric=0, aggregate_metric=0, builder_greenness=[
                  greenness_pb2.AggregateGreenness.Greenness(
                      builder='builder1-snapshot',
                      metric=0,
                      build_metric=0,
                  )
              ]))

  yield api.test(
      'unrelated-package-failure-but-red-on-snapshot',
      api.test_util.test_orchestrator(output_properties={
          'child_build_info': child_build_info
      }).build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES
                      )
                  ])
          }),
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
      ], 'analyzing build results.get tot failure builders.buildbucket.search'),
      api.properties(expected_retryable=[],
                     expected_outstanding=['builder1-cq']),
      api.post_process(post_process.DropExpectation),
  )
