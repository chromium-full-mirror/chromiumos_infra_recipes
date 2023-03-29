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
  api.paygen_orchestration.run_paygen_builders(paygen_requests)


test_bbids = [str(8922054662172514000 + i) for i in range(805)]


def GenTests(api: RecipeTestApi):

  yield api.test('basic', api.post_process(post_process.DropExpectation))

  yield api.test(
      'conductor',
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
