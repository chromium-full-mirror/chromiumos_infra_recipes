# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

from PB.recipes.chromeos.paygen import PaygenProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'conductor',
    'paygen_orchestration',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  # Test 201 gen requests (higher than bb.schedule's chunk size max of 200).
  gen_requests = api.paygen_orchestration.test_api.EXAMPLE_GEN_REQUESTS * 201

  paygen_requests = [
      PaygenProperties.PaygenRequest(generation_request=gen_request)
      for gen_request in gen_requests
  ]
  api.paygen_orchestration.run_paygen_builders(
      paygen_requests, override_qs_account='custom_qs_account')


test_bbids = [str(8922054662172514000 + i) for i in range(805)]


def GenTests(api: RecipeTestApi):

  yield api.test(
      'basic',
      api.post_check(post_process.LogContains, 'running children.schedule',
                     'request', ['"override_qs_account": "custom_qs_account"']),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'conductor-no-retries',
      api.properties(
          **{
              '$chromeos/conductor': {
                  'enable_conductor': True,
                  'collect_configs': {
                      'paygen': {},
                  },
              },
          }),
      api.conductor.set_collect_output(test_bbids,
                                       step_name='running children'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'conductor-retries',
      api.properties(
          **{
              '$chromeos/conductor': {
                  'enable_conductor': True,
                  'collect_configs': {
                      'paygen': {},
                  },
              },
          }),
      # Don't return one of the original builds (8922054662172514000).
      api.conductor.set_collect_output(
          [str(8922054662172514001 + i) for i in range(804)],
          step_name='running children'),
      api.post_process(post_process.DropExpectation))
