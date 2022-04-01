# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

DEPS = [
    'recipe_engine/assertions',
    'cros_paygen',
]

from recipe_engine import post_process

from PB.recipes.chromeos.paygen import PaygenProperties


def RunSteps(api):
  # Test timeout settings (includes individual runs and orch).
  api.assertions.assertEqual(7 * 60 * 60,
                             api.cros_paygen.paygen_orchestrator_timeout_sec)

  gen_requests = api.cros_paygen.test_api.EXAMPLE_GEN_REQUESTS

  # No max DLC batch size.
  paygen_requests = [
      api.cros_paygen._create_paygen_request_dict(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_DELTA_DLC[0]),
      api.cros_paygen._create_paygen_request_dict(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_FULL_DLC[0]),
  ]
  actual_batches = api.cros_paygen._batch_paygen_request_dicts(paygen_requests)
  expected_batches = [[paygen_requests[0], paygen_requests[1]]]
  api.assertions.assertCountEqual(expected_batches, actual_batches)
  # Max DLC batch size of 1.
  api.cros_paygen._max_dlc_batch_size = 1
  actual_batches = api.cros_paygen._batch_paygen_request_dicts(paygen_requests)
  expected_batches = [[paygen_requests[0]], [paygen_requests[1]]]
  api.assertions.assertCountEqual(
      [y for y in expected_batches],
      [y for y in actual_batches])  # Last DLC batch size is smaller than max.
  api.cros_paygen._max_dlc_batch_size = 2
  paygen_requests = [
      api.cros_paygen._create_paygen_request_dict(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_FULL_DLC[0]),
      api.cros_paygen._create_paygen_request_dict(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_FULL_DLC[0]),
      api.cros_paygen._create_paygen_request_dict(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_FULL_DLC[0]),
      api.cros_paygen._create_paygen_request_dict(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_FULL_DLC[0]),
      api.cros_paygen._create_paygen_request_dict(
          api.cros_paygen.test_api.EXAMPLE_GEN_REQUEST_FULL_DLC[0]),
  ]
  actual_batches = api.cros_paygen._batch_paygen_request_dicts(paygen_requests)
  api.assertions.assertEqual(len(actual_batches[0]), 2)
  api.assertions.assertEqual(len(actual_batches[1]), 2)
  api.assertions.assertEqual(len(actual_batches[2]), 1)

  paygen_requests = [
      PaygenProperties.PaygenRequest(generation_request=gen_request)
      for gen_request in gen_requests
  ]
  api.cros_paygen.run_paygen_builders(paygen_requests)


def GenTests(api):

  yield api.test('basic', api.post_check(post_process.StatusSuccess))
