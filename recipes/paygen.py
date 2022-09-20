# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS payloads (AU deltas etc)."""

import datetime
import json

from RECIPE_MODULES.chromeos.util.util import exponential_retry

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'bot_scaling',
    'cros_build_api',
    'cros_infra_config',
    'cros_paygen',
    'cros_sdk',
    'cros_source',
    'cros_storage',
    'easy',
    'failures',
    'git',
    'gitiles',
    'naming',
    'src_state',
    'workspace_util',
]

from collections import namedtuple

from google.protobuf.json_format import MessageToDict

from recipe_engine.recipe_api import StepFailure
from recipe_engine import post_process

import PB.chromiumos.common as common_pb2
from PB.chromite.api.payload import GenerationResponse
from PB.recipes.chromeos.paygen import AutoupdateTestConfig
from PB.recipes.chromeos.paygen import PaygenProperties
from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)

PROPERTIES = PaygenProperties

# Number of total tries on individual paygen jobs to attempt.
_PAYGEN_TRY_COUNT = 2


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
    # Since paygen supports being given a bucket for the source image, we need
    # need to make sure to use that same bucket for testing so we can actually
    # download the source image and use it. (This primarily impacts staging,
    # where we may not have older versions in the throwaway bucket so we instead
    # use the prod bucket.)
    src_bucket = request.generation_request.src_unsigned_image.build.bucket or \
                 request.generation_request.tgt_unsigned_image.build.bucket
    tgt_payload = (
        # Notice FullPayload doesn't get a bucket. That's because a full payload
        # source is created in cros_paygen.create_paygen_test_config().
        api.cros_storage.FullPayload.parse_uri(response.remote_uri, milestone)
        or api.cros_storage.DeltaPayload.parse_uri(response.remote_uri,
                                                   milestone, src_bucket))
    for test_config in request.autoupdate_test_configs:
      paygen_test_configs.append(
          api.cros_paygen.create_paygen_test_config(
              tgt_payload, src_version=test_config.src_version,
              src_channel=test_config.src_channel,
              delta_type=test_config.delta_type,
              applicable_models=test_config.applicable_models,
              src_bucket=src_bucket))

    return paygen_test_configs


def RunSteps(api, properties):
  api.easy.log_parent_step()
  with api.failures.ignore_exceptions():
    api.bcid_reporter.report_stage('start')

  if api.cros_infra_config.is_staging:
    api.bot_scaling.drop_cpu_cores(min_cpus_left=2, max_drop_ratio=.75)

  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    with api.failures.ignore_exceptions():
      api.bcid_reporter.report_stage('fetch')
    with api.step.nest('initialization'):

      # Sync the paygen manifest group.
      api.cros_source.ensure_synced_cache(
          init_opts={'groups': ['paygen']},
          cache_path_override=api.src_state.workspace_path,
      )

      config_path = api.cros_source.workspace_path.join('src/config-internal')

      # Repo leaves directories around... See: project.py "DeleteWorktree".
      api.step('remove repo cruft', ['rm', '-rf', config_path])

      config_internal_branch = 'main' if (
          'snapshot' in api.cros_source.manifest_branch
      ) else api.cros_source.manifest_branch

      # Pull config-internal seperately. This repo has a huge history that we
      # can't delete (as it would break manifests). Therefore we want to clone
      # alone at depth=1.
      with api.step.nest('clone config-internal from {} branch'.format(
          config_internal_branch)):
        api.git.clone(
            'https://chrome-internal.googlesource.com/chromeos/config-internal',
            branch=config_internal_branch, target_path=config_path, depth=1)

      # Create chroot, with retries!
      @exponential_retry(retries=3, delay=datetime.timedelta(seconds=300))
      def _retry_chroot_init_wrapper():
        api.cros_sdk.create_chroot(version=None, use_image=False,
                                   timeout_sec=None)

      _retry_chroot_init_wrapper()


    # Set up holder objects.
    paygen_test_configs, payloads = [], []

    CallPair = namedtuple('CallPair', ['req', 'resp', 'call_count'])

    def _execute_paygen(req, semaphore):
      """Executes a paygen call to build-api, retrying to _PAYGEN_TRY_COUNT

      Returns:
        CallPair that contains the request and either the response, or the
            exception that was thrown, followed by the try count.
      """
      num_tries = 0
      last_err = None
      while num_tries < _PAYGEN_TRY_COUNT:
        try:
          with semaphore:
            suffix = '' if not num_tries else ' retry ({})'.format(num_tries)
            num_tries += 1
            # Make the call to generate payload.
            resp = api.cros_build_api.PayloadService.GeneratePayload(
                req.generation_request,
                name='making single payload{}'.format(suffix),
                step_text=api.naming.get_generation_request_title(
                    MessageToDict(req).get('generationRequest', {})))
            if resp.success:
              with api.failures.ignore_exceptions():
                abspath = api.path.abspath(resp.local_path)
                file_hash = api.file.file_hash(abspath, test_data='deadbeef')
                api.bcid_reporter.report_gcs(file_hash, resp.remote_uri)

            return CallPair(req, resp, num_tries)
        except StepFailure as e:
          last_err = e
      return CallPair(req, last_err, num_tries)

    with api.step.nest('doing paygen') as presentation:
      with api.failures.ignore_exceptions():
        api.bcid_reporter.report_stage('generating payloads')

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
          # TODO(b/217973414): Replace with MessageToJson once we don't need to
          # fix the separator spacing between py2 and py3 MessageToJson.
          pres.logs['request'] = json.dumps(
              MessageToDict(request), separators=(',', ': '), indent=2,
              sort_keys=True)
          # Execute build api endpoint for paygen.
          futures.append(
              api.m.futures.spawn(_execute_paygen, request,
                                  semaphore_for_requests))

      errors, total_retries = [], 0
      for f in api.m.futures.iwait(futures):
        f_result = f.result()

        response = f_result.resp
        request = f_result.req

        total_retries += f_result.call_count - 1

        # If an exception was thrown, add it to errors and move on to the next
        # request.
        if isinstance(response, StepFailure):
          errors.append(f_result)
          continue

        if response.failure_reason:
          # See go/rubik-must-paygen-minios for more info about minios skips.
          if response.failure_reason == GenerationResponse.NOT_MINIOS_COMPATIBLE:
            presentation.step_text = 'not compatible with miniOS, skipping'
            continue
          else:
            errors.append(
                CallPair(request, StepFailure(response.failure_reason),
                         f_result.call_count))

        report_payload = api.cros_paygen.create_paygen_build_report_payload(
            request, response.remote_uri)
        if report_payload:
          payloads.append(report_payload)

        test_configs = _set_up_test_configs(api, request, response)
        if test_configs:
          paygen_test_configs.extend(test_configs)

      api.easy.set_properties_step(
          payloads=[MessageToDict(payload) for payload in payloads])
      api.easy.set_properties_step(paygen_retries=total_retries)

      if errors:
        raise StepFailure('paygen failed with errors: {}'.format('\n'.join([
            '{request} - {error}'.format(
                request=api.naming.get_generation_request_title(
                    MessageToDict(x.req).get('generationRequest', {})),
                error=x.resp) for x in errors
        ])))

    with api.failures.ignore_exceptions():
      api.bcid_reporter.report_stage('upload-complete')
    if paygen_test_configs:
      # Test all paygens.
      with api.step.nest('testing paygen'):
        api.cros_paygen.schedule_au_tests(paygen_test_configs)


# TODO(crbug.com/1157719): Improve testing mock data. There is a disconnect
# between the mock data and the Recipe logic. For example, a call to
# GeneratePayloads with no request still returns a successful response.
def GenTests(api):

  def generate_payload_response(api, is_success=True, local_path='',
                                remote_uri='', failure_reason=None, retcode=0,
                                retry=0):
    suffix = '' if not retry else ' retry ({})'.format(retry)
    data = json.dumps(
        dict(success=is_success, local_path=local_path, remote_uri=remote_uri,
             failure_reason=failure_reason), sort_keys=True)
    return api.cros_build_api.set_api_return(
        parent_step_name='doing paygen.running paygen operations in parallel',
        step_name='making single payload{}'.format(suffix), data=data,
        retcode=retcode)

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
  payload_json_data = """{
  "appid": "appid",
  "metadata_signature": "signature",
  "metadata_size": 1337,
  "size": 1234,
  "source_version": "1.2.3",
  "target_version": "4.5.6",
  "sha256_hex": "deadbeef",
  "is_delta": true
}"""

  yield api.test(
      'dryrun',
      api.buildbucket.generic_build(builder="staging-paygen", bucket='staging'),
      api.properties(
          PaygenProperties(requests=[
              dict(
                  generation_request=api.cros_paygen
                  .EXAMPLE_GEN_REQUEST_FULL_DLC[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ])
          ]), **{
              "$chromeos/cros_infra_config":
                  CrosInfraConfigProperties(release_tot_builds_snapshot=True)
          }),
      generate_payload_response(api),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.MustRun,
                     'initialization.clone config-internal from main branch'),
      api.post_check(post_process.DoesNotRun, 'testing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
      api.post_check(post_process.StatusSuccess),
      # api.post_process(post_process.DropExpectation),
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
      api.step_data('doing paygen.gsutil cat {}.json'.format(full_payload_uri),
                    stdout=api.raw_io.output(payload_json_data)),
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
      api.post_check(post_process.StatusSuccess),
      # api.post_process(post_process.DropExpectation),
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
      api.step_data('doing paygen.gsutil cat {}.json'.format(full_payload_uri),
                    stdout=api.raw_io.output(payload_json_data)),
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
      api.post_check(post_process.StatusSuccess),
      # api.post_process(post_process.DropExpectation),
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
      api.post_check(post_process.StatusFailure),
      # api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'failed-paygen-exception',
      api.properties(
          PaygenProperties(requests=[
              dict(generation_request=api.cros_paygen
                   .EXAMPLE_GEN_REQUEST_FULL_DLC[0])
          ])),
      generate_payload_response(api, is_success=False, retcode=3,
                                failure_reason=2),
      generate_payload_response(api, is_success=False, retcode=3,
                                failure_reason=2, retry=1),
      api.post_check(post_process.StepFailure, 'doing paygen'),
      api.post_check(post_process.DoesNotRun, 'testing paygen'),
      api.post_check(post_process.StatusFailure),
      # api.post_process(post_process.DropExpectation),
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
      api.post_check(post_process.StatusSuccess),
      # api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-testing',
      api.properties(
          PaygenProperties(requests=[
              dict(generation_request=api.cros_paygen
                   .EXAMPLE_GEN_REQUESTS_DELTA_N2N[0])
          ])),
      api.step_data('doing paygen.gsutil cat {}.json'.format(full_payload_uri),
                    stdout=api.raw_io.output(payload_json_data)),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
      api.post_check(post_process.StatusSuccess),
      # api.post_process(post_process.DropExpectation),
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
      api.step_data('doing paygen.gsutil cat {}.json'.format(full_payload_uri),
                    stdout=api.raw_io.output(payload_json_data)),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.MustRun,
                     'testing paygen.buildbucket.schedule'),
      api.post_check(post_process.StatusSuccess),
      # api.post_process(post_process.DropExpectation),
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
      api.step_data('doing paygen.gsutil cat {}.json'.format(full_payload_uri),
                    stdout=api.raw_io.output(payload_json_data)),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
      api.post_check(post_process.StatusFailure),
      # api.post_process(post_process.DropExpectation),
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
      api.step_data('doing paygen.gsutil cat {}.json'.format(full_payload_uri),
                    stdout=api.raw_io.output(payload_json_data)),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule'),
      api.post_check(post_process.StatusFailure),
      # api.post_process(post_process.DropExpectation),
  )
