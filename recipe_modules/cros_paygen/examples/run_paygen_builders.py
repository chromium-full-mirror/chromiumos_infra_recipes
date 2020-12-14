# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_paygen',
]

import json

from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties


def RunSteps(api):
  gen_requests = api.cros_paygen.test_api.EXAMPLE_GEN_REQUESTS
  configured_payloads = [
      json.loads(api.cros_paygen.test_api.EXAMPLE_SINGLE_PAYGEN_CONFIG)
  ]

  # Test sorting GenerationRequests.
  full, delta, non = api.cros_paygen._categorize_generation_requests(
      gen_requests)
  api.assertions.assertEqual([1, 2, 4], [len(full), len(delta), len(non)])

  # Test scheduling full test payloads.
  # Respect config
  actual_full_schedule_reqs = api.cros_paygen._schedule_full_test_payloads(
      full, configured_payloads)
  expected_full_tests = [
      api.cros_paygen._create_bb_schedule_request(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_FULL_UNSIGNED[0],
          [api.cros_paygen.test_api.EXAMPLE_TEST_REQUEST_FULL_N2N])
  ]
  api.assertions.assertItemsEqual(
      [y.properties for y in expected_full_tests],
      [y.properties for y in actual_full_schedule_reqs])
  # Force tests
  actual_full_schedule_reqs = api.cros_paygen._schedule_full_test_payloads(
      full, configured_payloads, PaygenOrchestratorProperties.FORCE_TESTS)
  expected_full_tests = [
      api.cros_paygen._create_bb_schedule_request(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_FULL_UNSIGNED[0], [
              api.cros_paygen.test_api.EXAMPLE_TEST_REQUEST_FULL_N2N,
              api.cros_paygen.test_api.EXAMPLE_TEST_REQUEST_FULL_OMAHA
          ])
  ]
  api.assertions.assertItemsEqual(
      [y.properties for y in expected_full_tests],
      [y.properties for y in actual_full_schedule_reqs])
  # Force no tests
  actual_full_schedule_reqs = api.cros_paygen._schedule_full_test_payloads(
      full, configured_payloads, PaygenOrchestratorProperties.FORCE_NO_TESTS)
  expected_full_tests = [
      api.cros_paygen._create_bb_schedule_request(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_FULL_UNSIGNED[0])
  ]
  api.assertions.assertItemsEqual(
      [y.properties for y in expected_full_tests],
      [y.properties for y in actual_full_schedule_reqs])

  # Test scheduling delta test payloads.
  # Respect config
  actual_delta_schedule_reqs = api.cros_paygen._schedule_delta_test_payloads(
      delta, configured_payloads)
  expected_delta_tests = [
      api.cros_paygen._create_bb_schedule_request(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_DELTA_N2N[0],
          [api.cros_paygen.test_api.EXAMPLE_TEST_REQUEST_DELTA_N2N]),
      api.cros_paygen._create_bb_schedule_request(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_DELTA_UNSIGNED[0])
  ]
  api.assertions.assertItemsEqual(
      [y.properties for y in expected_delta_tests],
      [y.properties for y in actual_delta_schedule_reqs])
  # Force tests
  actual_delta_schedule_reqs = api.cros_paygen._schedule_delta_test_payloads(
      delta, configured_payloads, PaygenOrchestratorProperties.FORCE_TESTS)
  expected_delta_tests = [
      api.cros_paygen._create_bb_schedule_request(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_DELTA_UNSIGNED[0],
          [api.cros_paygen.test_api.EXAMPLE_TEST_REQUEST_DELTA_OMAHA]),
      api.cros_paygen._create_bb_schedule_request(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_DELTA_N2N[0],
          [api.cros_paygen.test_api.EXAMPLE_TEST_REQUEST_DELTA_N2N]),
  ]
  api.assertions.assertItemsEqual(
      [y.properties for y in expected_delta_tests],
      [y.properties for y in actual_delta_schedule_reqs])
  # Force no tests
  actual_delta_schedule_reqs = api.cros_paygen._schedule_delta_test_payloads(
      delta, configured_payloads, PaygenOrchestratorProperties.FORCE_NO_TESTS)
  expected_delta_tests = [
      api.cros_paygen._create_bb_schedule_request(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_DELTA_UNSIGNED[0]),
      api.cros_paygen._create_bb_schedule_request(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_DELTA_N2N[0])
  ]
  api.assertions.assertItemsEqual(
      [y.properties for y in expected_delta_tests],
      [y.properties for y in actual_delta_schedule_reqs])

  api.cros_paygen.run_paygen_builders(gen_requests, configured_payloads)


def GenTests(api):

  yield api.test('basic')
