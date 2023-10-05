# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES

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
  orch.orchestrator.child_specs.add().name = 'builder1'
  orch.orchestrator.child_specs.add().name = 'builder2'
  orch.orchestrator.child_specs.add().name = 'builder4'
  orch.orchestrator.child_specs.add().name = 'builder5'
  orch.orchestrator.child_specs.add().name = 'builder6-cq'

  child_build_info = [
      {
          'builder': {
              'builder': 'builder1'
          },
          'status': 'SUCCESS',
          'relevant': True
      },
      {
          'builder': {
              'builder': 'builder2'
          },
          'status': 'FAILURE',
          'relevant': True
      },
      {
          'builder': {
              'builder': 'builder3'
          },
          'status': 'FAILURE',
          'relevant': True
      },
      {
          'builder': {
              'builder': 'builder4'
          },
          'status': 'SUCCESS',
          'relevant': False
      },
      {
          'builder': {
              'builder': 'builder5'
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
  ]
  yield api.test(
      'removed-verifier',
      api.test_util.test_orchestrator(output_properties={
          'child_build_info': child_build_info
      }).build,
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          expected_success=['builder1'], expected_retryable=['builder3'],
          expected_outstanding=['builder2', 'builder5', 'builder6-slim-cq']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'infra-failure-experiment-feature',
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
      api.properties(expected_success=['builder1'],
                     expected_retryable=['builder3', 'builder5'],
                     expected_outstanding=['builder2', 'builder6-slim-cq']),
      api.post_process(post_process.DropExpectation),
  )
