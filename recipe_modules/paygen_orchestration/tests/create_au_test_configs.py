# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

import json
from typing import List
from typing import Tuple

from PB.chromite.api.payload import GenerationRequest
from PB.recipes.chromeos.paygen import AutoupdateTestConfig
from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties
from recipe_engine.recipe_api import Property
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'paygen_orchestration',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    # Recipes seem unable to handle unhashable inline-defined PROPERTIES, such
    # as proto messages and lists. Serialize proto messages, and use tuples for
    # repeated fields.
    'gen_req_ser':
        Property(
            kind=bytes,
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
    'au_testing_models':
        Property(
            kind=list,
            help='List of string to be used for au_testing_models.',
            default=[],
        ),
    'au_fsi_testing_models':
        Property(
            kind=list,
            help='List of string to be used for au_fsi_testing_models.',
            default=[],
        ),
}


def RunSteps(
    api: RecipeApi, gen_req_ser: str, expected_test_configs_ser: Tuple[str],
    delta_test_override: PaygenOrchestratorProperties.PayloadTestsOverride,
    full_test_override: PaygenOrchestratorProperties.PayloadTestsOverride,
    fsi: bool, au_testing_models: List[str], au_fsi_testing_models: List[str]):
  api.assertions.maxDiff = None
  with api.step.nest('setup'):
    configured_payloads = [
        json.loads(
            api.paygen_orchestration.test_api.EXAMPLE_SINGLE_PAYGEN_CONFIG)
    ]
    if fsi:
      configured_payloads[0]['delta_type'] = 'FSI'
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
    actual_test_configs = api.paygen_orchestration.create_au_test_configs(
        gen_req, configured_payloads, au_testing_models, au_fsi_testing_models,
        delta_test_override=delta_test_override,
        full_test_override=full_test_override)
  with api.step.nest('assert'):
    api.assertions.assertCountEqual(actual_test_configs, expected_test_configs)


def GenTests(api: RecipeTestApi):

  def create_properties(
      gen_req: GenerationRequest,
      expected_test_configs: List[AutoupdateTestConfig],
      delta_test_override: PaygenOrchestratorProperties
      .PayloadTestsOverride = 0,
      full_test_override: PaygenOrchestratorProperties.PayloadTestsOverride = 0,
      fsi: bool = False, au_testing_models: List[str] = None,
      au_fsi_testing_models: List[str] = None) -> TestData:
    au_testing_models = au_testing_models or []
    au_fsi_testing_models = au_fsi_testing_models or []
    gen_req_ser = gen_req.SerializeToString()
    expected_test_configs_ser = tuple(
        etc.SerializeToString() for etc in expected_test_configs)
    return api.properties(
        gen_req_ser=gen_req_ser,
        expected_test_configs_ser=expected_test_configs_ser,
        delta_test_override=delta_test_override,
        full_test_override=full_test_override, fsi=fsi,
        au_testing_models=api.paygen_orchestration.AU_TESTING_MODELS,
        au_fsi_testing_models=api.paygen_orchestration.ALL_EXPORTED_MODELS)

  yield api.test(
      'delta-(m2n)-respect-configs',
      create_properties(
          api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0], []),
  )

  yield api.test(
      'delta-(m2n)-force-tests',
      create_properties(
          api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0],
          [api.paygen_orchestration.EXAMPLE_TEST_REQUEST_DELTA_OMAHA],
          delta_test_override=PaygenOrchestratorProperties.FORCE_TESTS),
  )

  yield api.test(
      'delta-(fsi)-force tests',
      create_properties(
          api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0],
          [api.paygen_orchestration.EXAMPLE_TEST_REQUEST_DELTA_FSI],
          delta_test_override=PaygenOrchestratorProperties.FORCE_TESTS,
          fsi=True),
  )

  yield api.test(
      'delta-(m2n)-force-no-tests',
      create_properties(
          api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0], [],
          delta_test_override=PaygenOrchestratorProperties.FORCE_NO_TESTS),
  )

  yield api.test(
      'delta-(n2n)-force-tests',
      create_properties(
          api.paygen_orchestration.get_example_gen_requests_delta_n2n()[0],
          [api.paygen_orchestration.EXAMPLE_TEST_REQUEST_DELTA_N2N],
          delta_test_override=PaygenOrchestratorProperties.FORCE_TESTS),
  )

  yield api.test(
      'full-respect-configs',
      create_properties(
          api.paygen_orchestration.get_example_gen_requests_full_unsigned()[0],
          [api.paygen_orchestration.EXAMPLE_TEST_REQUEST_FULL_N2N]),
  )

  yield api.test(
      'full-minios-skipped',
      create_properties(
          api.paygen_orchestration.get_example_gen_requests_full_unsigned()[1],
          []))

  yield api.test(
      'full-force-tests',
      create_properties(
          api.paygen_orchestration.get_example_gen_requests_full_unsigned()[0],
          [
              api.paygen_orchestration.EXAMPLE_TEST_REQUEST_FULL_N2N,
              api.paygen_orchestration.EXAMPLE_TEST_REQUEST_FULL_OMAHA
          ], full_test_override=PaygenOrchestratorProperties.FORCE_TESTS),
  )

  yield api.test(
      'full-force-no-tests',
      create_properties(
          api.paygen_orchestration.get_example_gen_requests_full_unsigned()[0],
          [], full_test_override=PaygenOrchestratorProperties.FORCE_NO_TESTS),
  )

  yield api.test(
      'not-unsigned-image',
      create_properties(
          api.paygen_orchestration.get_example_gen_requests_delta_signed()[0],
          []),
  )

  yield api.test(
      'unsigned-not-test-image',
      create_properties(
          api.paygen_orchestration
          .EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED_RECOVERY[0], []),
  )
