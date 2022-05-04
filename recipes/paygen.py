# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS payloads (AU deltas etc)."""

import json

PYTHON_VERSION_COMPATIBILITY = 'PY2'

DEPS = [
    'recipe_engine/futures',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
    'cros_paygen',
    'cros_sdk',
    'cros_source',
    'cros_storage',
    'easy',
    'gitiles',
    'naming',
    'src_state',
    'workspace_util',
]

from collections import namedtuple

from google.protobuf.json_format import MessageToDict, MessageToJson

from recipe_engine.recipe_api import StepFailure
from recipe_engine import post_process

import PB.chromiumos.common as common_pb2
from PB.chromite.api.payload import GenerationResponse
from PB.recipes.chromeos.paygen import AutoupdateTestConfig
from PB.recipes.chromeos.paygen import PaygenProperties

PROPERTIES = PaygenProperties


def _set_up_test_configs(api, request, response):
  """Set up test configs for a paygen response, if applicable.

  Given a PaygenRequest and a GenerationResponse, determine if this payload
  should have testing applied and if so set up and return the test configs
  to be scheduled.

  Args:
    api (RecipeApi): recipe api to use for step operations.
    request (PaygenRequest): request object to introspect.
    response (GenerationResponse): response from payload generation.

  Returns:
    [PaygenTestConfig] list of paygen test configs to schedule.
  """
  with api.step.nest('setting up paygen test config') as presentation:
    if request.generation_request.dryrun:
      presentation.step_text = 'dry run, skip testing'
      return
    if not request.autoupdate_test_configs:
      presentation.step_text = 'no test configured, skip testing'
      return
    if request.generation_request.WhichOneof(
        'tgt_image_oneof') != 'tgt_unsigned_image':
      raise StepFailure(
          'autoupdate tests can only be run on payloads with unsigned images')

    paygen_test_configs = []

    milestone = request.generation_request.tgt_unsigned_image.milestone
    tgt_payload = (
        api.cros_storage.FullPayload.parse_uri(response.remote_uri,
                                               milestone) or
        api.cros_storage.DeltaPayload.parse_uri(response.remote_uri, milestone))
    for test_config in request.autoupdate_test_configs:
      paygen_test_configs.append(
          api.cros_paygen.create_paygen_test_config(
              tgt_payload, src_version=test_config.src_version,
              src_channel=test_config.src_channel,
              delta_type=test_config.delta_type,
              applicable_models=test_config.applicable_models))

    return paygen_test_configs


def RunSteps(api, properties):
  api.easy.log_parent_step()

  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    with api.step.nest('initialization'):

      # Sync chromite and config-internal only.
      api.cros_source.ensure_synced_cache(
          projects=['chromeos/config-internal', 'chromiumos/chromite'],
          cache_path_override=api.src_state.workspace_path,
      )

      # Create chroot.
      api.cros_sdk.create_chroot(version=None, use_image=False,
                                 timeout_sec=None)

    # Set up holder of paygen test configs.
    paygen_test_configs = []
    # Set up holder of paygen uris.
    paygen_uris = []

    CallPair = namedtuple('CallPair', ['req', 'resp'])

    def _execute_paygen(req, semaphore):
      """Return PayloadService.GeneratePayload with the request."""
      with semaphore:
        resp = api.cros_build_api.PayloadService.GeneratePayload(
            req.generation_request, name='making single payload',
            step_text=api.naming.get_generation_request_title(
                MessageToDict(req).get('generationRequest', {})))

        return CallPair(req, resp)

    with api.step.nest('doing paygen') as presentation:

      # Get max number of concurrent requests - None is unlimited.
      max_concurrent_requests = properties.max_concurrent_requests or len(
          properties.requests)
      semaphore_for_requests = api.futures.make_bounded_semaphore(
          max_concurrent_requests)
      presentation.step_text = 'number of concurrent requests: {}'.format(
          max_concurrent_requests)

      # Iterate through every request.
      futures = []
      with api.step.nest('running paygen operations in parallel') as pres:
        for request in properties.requests:
          pres.logs['request'] = MessageToJson(request)
          # Execute build api endpoint for paygen.
          futures.append(
              api.m.futures.spawn(_execute_paygen, request,
                                  semaphore_for_requests))

      for f in api.m.futures.iwait(futures):
        f_result = f.result()

        response = f_result.resp
        request = f_result.req

        paygen_uris.append(response.remote_uri)

        if response.failure_reason:
          # See go/rubik-must-paygen-minios for more info about minios skips.
          if response.failure_reason == GenerationResponse.NOT_MINIOS_COMPATIBLE:
            presentation.step_text = 'not compatible with miniOS, skipping'
            continue
          else:
            raise StepFailure('paygen failed with error {}'.format(
                response.failure_reason))

        test_configs = _set_up_test_configs(api, request, response)
        if test_configs:
          paygen_test_configs.extend(test_configs)

    api.easy.set_properties_step(payload_uris=paygen_uris)

    if paygen_test_configs:
      # Test all paygens.
      with api.step.nest('testing paygen'):
        api.cros_paygen.schedule_au_tests(paygen_test_configs)


# TODO(crbug.com/1157719): Improve testing mock data. There is a disconnect
# between the mock data and the Recipe logic. For example, a call to
# GeneratePayloads with no request still returns a successful response.
def GenTests(api):

  def generate_payload_response(api, is_success=True, local_path='',
                                remote_uri='', failure_reason=None, retcode=0):
    data = json.dumps(
        dict(success=is_success, local_path=local_path, remote_uri=remote_uri,
             failure_reason=failure_reason))
    return api.cros_build_api.set_api_return(
        parent_step_name='doing paygen.running paygen operations in parallel',
        step_name='making single payload', data=data, retcode=retcode)

  def StepTextEquals(check, step_odict, step, expected):
    """Check that the step's text equals given value.

    Args:
      step (str) - The step to check the step text of.
      expected (str) - The expected text of the step.

    Usage:
      yield TEST + \
          api.post_process(StepTextEquals, 'step-name', 'expected-text')
    """
    check(step_odict[step].step_text == expected)

  full_payload_uri = (
      'gs://test-bucket/canary-channel/zork/12345.0.0/payloads/'
      'chromeos_12345.0.0_zork_canary-channel_full_test.bin-abc')

  yield api.test(
      'dryrun',
      api.properties(
          PaygenProperties(requests=[
              dict(
                  generation_request=api.cros_paygen
                  .EXAMPLE_GEN_REQUEST_FULL_DLC[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ])
          ])),
      generate_payload_response(api),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun, 'testing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'multiple-dryruns',
      api.properties(
          PaygenProperties(requests=[
              dict(
                  generation_request=api.cros_paygen
                  .EXAMPLE_GEN_REQUEST_FULL_DLC[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ]),
              dict(
                  generation_request=api.cros_paygen
                  .EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED[0],
                  autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ])
          ])),
      generate_payload_response(api),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.making single payload'
      ),
      api.post_check(
          StepTextEquals,
          'doing paygen.running paygen operations in parallel.making single payload',
          'DLC (termina-dlc) stable-channel | Full (13425.90.0)'),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.making single payload (2)'
      ),
      api.post_check(
          StepTextEquals,
          'doing paygen.running paygen operations in parallel.making single payload (2)',
          'Unsigned IMAGE_TYPE_TEST stable-channel | Full (13425.90.0)'),
      api.post_check(post_process.DoesNotRun, 'testing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'multiple-runs-no-concurrency',
      api.properties(
          PaygenProperties(
              requests=[
                  dict(
                      generation_request=api.cros_paygen
                      .EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                      autoupdate_test_configs=[
                          AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                               applicable_models=['woomax'])
                      ]),
                  dict(
                      generation_request=api.cros_paygen
                      .EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                      autoupdate_test_configs=[
                          AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                               applicable_models=['woomax'])
                      ])
              ], max_concurrent_requests=1)),
      generate_payload_response(api),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.making single payload'
      ),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.making single payload (2)'
      ),
      api.post_check(post_process.DoesNotRun, 'testing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'failed-paygen',
      api.properties(
          PaygenProperties(requests=[
              dict(generation_request=api.cros_paygen
                   .EXAMPLE_GEN_REQUEST_FULL_DLC[0])
          ])),
      generate_payload_response(api, is_success=False, retcode=2,
                                failure_reason=2),
      api.post_check(post_process.StepFailure, 'doing paygen'),
      api.post_check(post_process.DoesNotRun, 'testing paygen'),
  )

  yield api.test(
      'failed-minios',
      api.properties(
          PaygenProperties(requests=[
              dict(generation_request=api.cros_paygen
                   .EXAMPLE_GEN_REQUEST_FULL_DLC[0])
          ])),
      generate_payload_response(
          api, is_success=False, retcode=2,
          failure_reason=GenerationResponse.NOT_MINIOS_COMPATIBLE),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun, 'testing paygen'),
  )

  yield api.test(
      'no-testing',
      api.properties(
          PaygenProperties(requests=[
              dict(generation_request=api.cros_paygen
                   .EXAMPLE_GEN_REQUESTS_DELTA_N2N[0])
          ])),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'with-testing',
      api.gitiles.get_file(api.cros_paygen.TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.properties(
          PaygenProperties(requests=[
              dict(
                  generation_request=api.cros_paygen
                  .EXAMPLE_GEN_REQUESTS_DELTA_N2N[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(src_version='123',
                                           src_channel='canary-channel',
                                           delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax']),
                      AutoupdateTestConfig(src_version='123',
                                           src_channel='canary-channel',
                                           delta_type=common_pb2.OMAHA,
                                           applicable_models=['other']),
                  ])
          ])),
      api.cros_storage.test_listing(
          'doing paygen.setting up paygen test config.discover gs artifacts.gsutil list',
          full_payload_uri,
      ),
      api.cros_storage.test_listing(
          'doing paygen.setting up paygen test config.discover gs artifacts (2).gsutil list',
          full_payload_uri,
      ),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.MustRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'mismatched-payload-and-testing-config',
      api.properties(
          PaygenProperties(requests=[
              dict(
                  generation_request=api.cros_paygen
                  .EXAMPLE_GEN_REQUESTS_DELTA_N2N[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ])
          ])),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )

  yield api.test(
      'mistmatch-non-test-payload-with-testing-config',
      api.properties(
          PaygenProperties(requests=[
              dict(
                  generation_request=api.cros_paygen
                  .EXAMPLE_GEN_REQUEST_DELTA_DLC[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ])
          ])),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
  )
