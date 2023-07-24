# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs

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
  ]
  yield api.test(
      'removed-verifier',
      api.test_util.test_orchestrator(output_properties={
          'child_build_info': child_build_info
      }).build,
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(expected_success=['builder1'],
                     expected_retryable=['builder3'],
                     expected_outstanding=['builder2']),
      api.post_process(post_process.DropExpectation),
  )
