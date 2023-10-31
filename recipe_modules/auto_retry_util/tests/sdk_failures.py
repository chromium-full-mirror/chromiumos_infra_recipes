# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests involving SDK failure retries."""

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_RETRY_SDK_FAILURES

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
  orch.orchestrator.child_specs.add().name = 'builder3-cq'

  yield api.test(
      'retry-with-other-successful-builds',
      api.test_util.test_orchestrator(
          output_properties={
              'child_build_info': [
                  {
                      'builder': {
                          'builder': 'builder1-cq'
                      },
                      'id': '123',
                      'status': 'SUCCESS',
                      'relevant': True
                  },
                  {
                      'builder': {
                          'builder': 'builder2-cq'
                      },
                      'id': '456',
                      'status': 'FAILURE',
                      'relevant': True
                  },
                  {
                      'builder': {
                          'builder': 'builder3-cq'
                      },
                      'id': '789',
                      'status': 'FAILURE',
                      'relevant': True
                  },
              ]
          }).build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_SDK_FAILURES)
                  ])
          }),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      # builder2-cq has a SDK failure, builder3-cq has a different failure. Only
      # expect builder2-cq to be retryable.
      api.buildbucket.simulated_get_multi([
          build_pb2.Build(
              id=456, builder=builder_common_pb2.BuilderID(
                  builder='builder2-cq',
              ), status=common_pb2.FAILURE,
              summary_markdown="Step('update sdk.call chromite.api.SdkService/Update.call build API script') (retcode: 3)"
          ),
          build_pb2.Build(
              id=789, builder=builder_common_pb2.BuilderID(
                  builder='builder3-cq',
              ), status=common_pb2.FAILURE, summary_markdown='other failure')
      ], step_name='analyzing build results.get sdk failures.buildbucket.get_multi'
                                         ),
      api.properties(expected_success=['builder1-cq'],
                     expected_retryable=['builder2-cq'],
                     expected_outstanding=['builder3-cq']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-retry-without-other-successful-builds',
      api.test_util.test_orchestrator(
          output_properties={
              'child_build_info': [
                  {
                      'builder': {
                          'builder': 'builder1-cq'
                      },
                      'id': '123',
                      'status': 'FAILURE',
                      'relevant': True
                  },
                  {
                      'builder': {
                          'builder': 'builder2-cq'
                      },
                      'id': '456',
                      'status': 'FAILURE',
                      'relevant': True
                  },
              ]
          }).build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_SDK_FAILURES)
                  ])
          }),
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(expected_success=[], expected_retryable=[],
                     expected_outstanding=['builder1-cq', 'builder2-cq']),
      api.post_process(post_process.DropExpectation),
  )
