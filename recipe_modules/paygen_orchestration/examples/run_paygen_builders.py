# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

import json

from PB.recipes.chromeos.paygen import PaygenProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
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


test_bbids = json.dumps([str(8922054662172514000 + i) for i in range(805)])


def GenTests(api: RecipeTestApi):

  yield api.test('basic', api.post_check(post_process.StatusSuccess),
                 api.post_process(post_process.DropExpectation))

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
      api.step_data('running children.read output json',
                    api.file.read_text(test_bbids)),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))
