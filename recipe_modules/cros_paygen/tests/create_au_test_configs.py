# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_paygen',
]

import json

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

from PB.chromite.api.payload import GenerationRequest
from PB.recipes.chromeos.paygen import AutoupdateTestConfig
from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties

PYTHON_VERSION_COMPATIBILITY = 'PY2'

PROPERTIES = {
    # Recipes seem unable to handle unhashable inline-defined PROPERTIES, such
    # as proto messages and lists. Serialize proto messages, and use tuples for
    # repeated fields.
    'gen_req_ser':
        Property(
            kind=str,
            help='The serialized GenerationRequest for which to create tests.',
            default=''),
    'expected_test_configs_ser':
        Property(
            help='Tuple of serialized AutoupdateTestConfigs we expect to see.',
            default='',
        ),
    'delta_test_override':
        Property(
            kind=int,
            help='Enum value to override the payload\'s delta testing config.',
            default=0,
        ),
    'full_test_override':
        Property(
            kind=int,
            help='Enum value to override the payload\'s full testing config.',
            default=0,
        ),
    'fsi':
        Property(
            kind=bool,
            help='Whether the configured_payload should be for an FSI payload.',
            default=False,
        ),
}


def RunSteps(api, gen_req_ser, expected_test_configs_ser, delta_test_override,
             full_test_override, fsi):
  api.assertions.maxDiff = None
  with api.step.nest('setup'):
    configured_payloads = [
        json.loads(api.cros_paygen.test_api.EXAMPLE_SINGLE_PAYGEN_CONFIG)
    ]
    if fsi:
      configured_payloads[0]['delta_type'] = 'FSI'
    api.cros_paygen._au_testing_models = \
        api.cros_paygen.test_api.AU_TESTING_MODELS
    api.cros_paygen._au_fsi_testing_models = \
        api.cros_paygen.test_api.ALL_EXPORTED_MODELS
    with api.step.nest('deserialize GenerationRequest'):
      gen_req = GenerationRequest()
      gen_req.ParseFromString(gen_req_ser)
    with api.step.nest('deserialize AutoupdateTestConfigs'):
      expected_test_configs = []
      for test_config_ser in expected_test_configs_ser:
        test_config = AutoupdateTestConfig()
        test_config.ParseFromString(test_config_ser)
        expected_test_configs.append(test_config)
  with api.step.nest('run'):
    actual_test_configs = api.cros_paygen.create_au_test_configs(
        gen_req, configured_payloads, delta_test_override=delta_test_override,
        full_test_override=full_test_override)
  with api.step.nest('assert'):
    api.assertions.assertCountEqual(actual_test_configs, expected_test_configs)


def GenTests(api):
  # TODO (b/223385038): Add tests for filtering by au_testing_configs
  # and fsi_testing_configs

  def create_properties(gen_req, expected_test_configs, delta_test_override=0,
                        full_test_override=0, fsi=False):
    gen_req_ser = gen_req.SerializeToString()
    expected_test_configs_ser = tuple(
        [etc.SerializeToString() for etc in expected_test_configs])
    return api.properties(gen_req_ser=gen_req_ser,
                          expected_test_configs_ser=expected_test_configs_ser,
                          delta_test_override=delta_test_override,
                          full_test_override=full_test_override, fsi=fsi)

  yield api.test(
      'delta-(m2n)-respect-configs',
      create_properties(api.cros_paygen.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0],
                        []), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'delta-(m2n)-force-tests',
      create_properties(
          api.cros_paygen.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0],
          [api.cros_paygen.EXAMPLE_TEST_REQUEST_DELTA_OMAHA],
          delta_test_override=PaygenOrchestratorProperties.FORCE_TESTS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'delta-(fsi)-force tests',
      create_properties(
          api.cros_paygen.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0],
          [api.cros_paygen.EXAMPLE_TEST_REQUEST_DELTA_FSI],
          delta_test_override=PaygenOrchestratorProperties.FORCE_TESTS,
          fsi=True), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'delta-(m2n)-force-no-tests',
      create_properties(
          api.cros_paygen.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0], [],
          delta_test_override=PaygenOrchestratorProperties.FORCE_NO_TESTS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'delta-(n2n)-force-tests',
      create_properties(
          api.cros_paygen.EXAMPLE_GEN_REQUESTS_DELTA_N2N[0],
          [api.cros_paygen.EXAMPLE_TEST_REQUEST_DELTA_N2N],
          delta_test_override=PaygenOrchestratorProperties.FORCE_TESTS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'full-respect-configs',
      create_properties(api.cros_paygen.EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED[0],
                        [api.cros_paygen.EXAMPLE_TEST_REQUEST_FULL_N2N]),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'full-minios-skipped',
      create_properties(api.cros_paygen.EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED[1],
                        []), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'full-force-tests',
      create_properties(
          api.cros_paygen.EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED[0], [
              api.cros_paygen.EXAMPLE_TEST_REQUEST_FULL_N2N,
              api.cros_paygen.EXAMPLE_TEST_REQUEST_FULL_OMAHA
          ], full_test_override=PaygenOrchestratorProperties.FORCE_TESTS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'full-force-no-tests',
      create_properties(
          api.cros_paygen.EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED[0], [],
          full_test_override=PaygenOrchestratorProperties.FORCE_NO_TESTS),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'not-unsigned-image',
      create_properties(api.cros_paygen.EXAMPLE_GEN_REQUESTS_DELTA_SIGNED[0],
                        []), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'unsigned-not-test-image',
      create_properties(
          api.cros_paygen.EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED_RECOVERY[0], []),
      api.post_check(post_process.StatusSuccess))
