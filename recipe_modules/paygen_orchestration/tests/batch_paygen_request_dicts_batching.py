# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

from PB.chromite.api.payload import GenerationRequest

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'paygen_orchestration',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    # Following the pattern from create_au_test_configs.py.
    'max_batch_size':
        Property(
            kind=int,
            help='Max batch size value.',
            default=0,
        ),
    'paygen_requests':
        Property(help='Tuple of serialized paygen requests for batching.',
                 default=''),
    'expected_batches':
        Property(
            help='Tuple of serialized paygen requests expected for the batches.',
            default=''),
}


def RunSteps(api, max_batch_size, paygen_requests, expected_batches):
  # Handle test setup (object parsing and whatnot).
  with api.step.nest('deserialize paygen_requests'):
    requests = []
    for request in paygen_requests:
      gen_req = GenerationRequest()
      gen_req.ParseFromString(request)
      requests.append(
          api.paygen_orchestration._create_paygen_request_dict(gen_req))
  if expected_batches:
    with api.step.nest('deserialize expected_batches'):
      batches = []
      for expected_batch in expected_batches:
        single_requests = []
        for single_request in expected_batch:
          gen_req = GenerationRequest()
          gen_req.ParseFromString(single_request)
          single_requests.append(
              api.paygen_orchestration._create_paygen_request_dict(gen_req))
        batches.append(single_requests)

  # Execute test.
  with api.step.nest('run test'):
    if max_batch_size:
      api.paygen_orchestration._max_dlc_batch_size = max_batch_size

    actual_batches = api.paygen_orchestration._batch_paygen_request_dicts(
        requests)
    api.assertions.assertEqual(batches, actual_batches)


def GenTests(api):

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
          ]])), api.post_check(post_process.StatusSuccess))

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
          ]])), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'max-batch-size-1', api.properties(max_batch_size=1),
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
               ]])), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'last-batch-smaller-than-max', api.properties(max_batch_size=2),
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
               ]])), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'n2n-batches-alongside-full',
      api.properties(
          paygen_requests=tuple(r.SerializeToString() for r in [
              api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED[0],
              api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_DELTA_N2N[0],
          ])),
      api.properties(
          expected_batches=tuple([[
              r.SerializeToString() for r in [
                  api.paygen_orchestration
                  .EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED[0],
                  api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_DELTA_N2N[0],
              ]
          ]])), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'n2n-without-matching-full',
      api.properties(
          paygen_requests=tuple([
              api.paygen_orchestration.EXAMPLE_GEN_REQUESTS_DELTA_N2N[0]
              .SerializeToString(),
          ])), api.post_check(post_process.StepFailure, 'run test'))
