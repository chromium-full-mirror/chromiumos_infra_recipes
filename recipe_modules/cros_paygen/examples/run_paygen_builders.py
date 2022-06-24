# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

DEPS = [
    'recipe_engine/assertions',
    'cros_paygen',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from recipe_engine import post_process

from PB.recipes.chromeos.paygen import PaygenProperties


def RunSteps(api):
  # Test 201 gen requests (higher than bb.schedule's chunk size max of 200).
  gen_requests = api.cros_paygen.test_api.EXAMPLE_GEN_REQUESTS * 201

  paygen_requests = [
      PaygenProperties.PaygenRequest(generation_request=gen_request)
      for gen_request in gen_requests
  ]
  api.cros_paygen.run_paygen_builders(paygen_requests)


def GenTests(api):

  yield api.test('basic', api.post_check(post_process.StatusSuccess),
                 api.post_process(post_process.DropExpectation))
