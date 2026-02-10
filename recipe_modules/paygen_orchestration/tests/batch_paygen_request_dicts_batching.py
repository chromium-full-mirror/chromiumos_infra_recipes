# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.payload import GenerationRequest
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'paygen_orchestration',
]



def RunSteps(api: RecipeApi):
  # Handle test setup (object parsing and whatnot).
  with api.step.nest('deserialize paygen_requests'):
    requests = []
    for request in api.properties['paygen_requests']:
      gen_req = GenerationRequest()
      gen_req.ParseFromString(request)
      requests.append(
          api.paygen_orchestration._create_paygen_request_dict(gen_req))
  if 'expected_batches' in api.properties:
    with api.step.nest('deserialize expected_batches'):
      batches = []
      for expected_batch in api.properties['expected_batches']:
        single_requests = []
        for single_request in expected_batch:
          gen_req = GenerationRequest()
          gen_req.ParseFromString(single_request)
          single_requests.append(
              api.paygen_orchestration._create_paygen_request_dict(gen_req))
        batches.append(single_requests)

  # Execute test.
  with api.step.nest('run test'):
    if 'max_batch_size' in api.properties:
      api.paygen_orchestration._max_dlc_batch_size = api.properties[
          'max_batch_size']

    actual_batches = api.paygen_orchestration._batch_paygen_request_dicts(
        requests, skip_n2n_batch=api.properties.get('skip_n2n_batch', False))
    api.assertions.assertEqual(batches, actual_batches)


def GenTests(api: RecipeTestApi):

  yield api.test(
      'basic-no-max-batch-size',
      api.properties(
          paygen_requests=tuple(r.SerializeToString() for r in [
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_DELTA_DLC[0],
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
          ])),
      api.properties(
          expected_batches=tuple([[
              r.SerializeToString() for r in [
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_DELTA_DLC[0],
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              ]
          ]])),
  )

  yield api.test(
      'chunked-schedule-requests',
      api.properties(
          paygen_requests=tuple(r.SerializeToString() for r in [
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_DELTA_DLC[0],
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
          ] * 300)),
      api.properties(
          expected_batches=tuple([[
              r.SerializeToString() for r in [
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_DELTA_DLC[0],
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              ] * 300
          ]])),
  )

  yield api.test(
      'max-batch-size-1',
      api.properties(max_batch_size=1),
      api.properties(
          paygen_requests=tuple(r.SerializeToString() for r in [
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_DELTA_DLC[0],
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
          ])),
      api.properties(
          expected_batches=tuple(
              [[
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_DELTA_DLC[0]
                  .SerializeToString()
              ],
               [
                   api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0]
                   .SerializeToString()
               ]])),
  )

  yield api.test(
      'last-batch-smaller-than-max',
      api.properties(max_batch_size=2),
      api.properties(
          paygen_requests=tuple(r.SerializeToString() for r in [
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
          ])),
      api.properties(
          expected_batches=tuple(
              [[
                  r.SerializeToString() for r in [
                      api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                      api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                  ]
              ],
               [
                   r.SerializeToString() for r in [
                       api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                       api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                   ]
               ],
               [
                   api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0]
                   .SerializeToString()
               ]])),
  )

  yield api.test(
      'n2n-batches-alongside-full',
      api.properties(
          paygen_requests=tuple(r.SerializeToString() for r in [
              api.paygen_orchestration.get_example_gen_requests_full_unsigned()
              [0],
              api.paygen_orchestration.get_example_gen_requests_delta_n2n()[0],
          ])),
      api.properties(
          expected_batches=tuple([[
              r.SerializeToString() for r in [
                  api.paygen_orchestration
                  .get_example_gen_requests_full_unsigned()[0],
                  api.paygen_orchestration.get_example_gen_requests_delta_n2n()
                  [0],
              ]
          ]])),
  )

  yield api.test(
      'n2n-without-matching-full',
      api.properties(
          paygen_requests=tuple([
              api.paygen_orchestration.get_example_gen_requests_delta_n2n()
              [0].SerializeToString(),
          ])), api.post_check(post_process.StepFailure, 'run test'),
      status='FAILURE')

  yield api.test(
      'n2n-batching-skipped', api.properties(skip_n2n_batch=True),
      api.properties(max_batch_size=8),
      api.properties(
          paygen_requests=tuple(r.SerializeToString() for r in [
              api.paygen_orchestration.get_example_gen_requests_full_unsigned()
              [0],
              api.paygen_orchestration.get_example_gen_requests_delta_n2n()[0],
          ])),
      api.properties(
          expected_batches=tuple([[
              api.paygen_orchestration.get_example_gen_requests_delta_n2n()
              [0].SerializeToString()
          ],
                                  [
                                      api.paygen_orchestration
                                      .get_example_gen_requests_full_unsigned()
                                      [0].SerializeToString()
                                  ]])),
      api.post_process(post_process.DropExpectation))
