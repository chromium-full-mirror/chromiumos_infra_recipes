# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS payloads (AU deltas etc)."""

import datetime
import json
from typing import Any, Callable, Dict, Optional, List

from RECIPE_MODULES.chromeos.util.util import exponential_retry
from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import MessageToJson

import PB.chromiumos.common as common_pb2
from PB.chromite.api.payload import GenerationResponse
from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import CrosInfraConfigProperties
from PB.recipes.chromeos.paygen import AutoupdateTestConfig
from PB.recipes.chromeos.paygen import PaygenProperties
from recipe_engine import post_process
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'bot_scaling',
    'cros_build_api',
    'cros_infra_config',
    'paygen_testing',
    'cros_sdk',
    'cros_source',
    'cros_storage',
    'easy',
    'failures',
    'future_utils',
    'git',
    'gitiles',
    'naming',
    'src_state',
    'workspace_util',
]

PROPERTIES = PaygenProperties

# Number of total tries on individual paygen jobs to attempt.
_PAYGEN_TRY_COUNT = 2


def RunSteps(api: RecipeApi, properties: PaygenProperties):
  api.easy.log_parent_step()
  with api.failures.ignore_exceptions():
    api.bcid_reporter.report_stage('start')

  if api.cros_infra_config.is_staging:
    api.bot_scaling.drop_cpu_cores(min_cpus_left=2, max_drop_ratio=.75)

  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    with api.failures.ignore_exceptions():
      api.bcid_reporter.report_stage('fetch')

    DoRunSteps(api, properties)


def DoRunSteps(api: RecipeApi, properties: PaygenProperties):
  # Set up builder state.
  initialize_directories(api, properties)
  # Set up holder objects.
  paygen_test_configs, payloads = [], []

  with api.step.nest('doing paygen') as presentation:
    with api.failures.ignore_exceptions():
      api.bcid_reporter.report_stage('compile')

    # Get max number of concurrent requests - None is unlimited.
    max_concurrent_requests = properties.max_concurrent_requests or len(
        properties.requests)
    presentation.step_text = 'number of concurrent requests: {}'.format(
        max_concurrent_requests)
    # Create a parallel runner with our max number of requests.
    paygen_parallel_runner = api.future_utils.create_parallel_runner(
        max_concurrent_requests)

    # Iterate through every request.
    with api.step.nest('running paygen operations in parallel') as pres:

      # Function to do a single paygen, given a request object.
      def do_a_paygen(req: PaygenProperties.PaygenRequest,
                      tries: int) -> GenerationResponse:
        """Generate a single payload, given a request object.

        Args:
          req: the request object to generate for.
          tries: the number try we're on.

        Returns:
          GenerationResponse from payload generation.
        """
        # Number of retries doesn't include the first try.
        suffix = '' if tries == 1 else ' retry ({})'.format(tries - 1)
        # Execute build api endpoint for paygen.
        return api.cros_build_api.PayloadService.GeneratePayload(
            req.generation_request,
            name='making single payload{}'.format(suffix),
            step_text=api.naming.get_generation_request_title(
                MessageToDict(req).get('generationRequest', {})))

      # Go through each request now and do paygen with our parallel runner.
      for request in properties.requests:
        pres.logs['request'] = MessageToJson(request)

        paygen_parallel_runner.run_function_async(
            do_a_paygen, request, success_handler=lambda resp, req=request,
            api=api: report_paygen_success_to_snoopy(api, req, resp)
            if not resp.failure_reason else None, try_count=_PAYGEN_TRY_COUNT)

    errors, total_retries = [], 0
    for paygen_response in paygen_parallel_runner.wait_for_and_get_responses():

      response = paygen_response.resp
      request = paygen_response.req

      total_retries += paygen_response.call_count - 1

      # If an exception was thrown, add it to errors and move on to the next
      # request.
      if paygen_response.errored:
        errors.append(paygen_response)
        continue

      if response.failure_reason:
        # See go/rubik-must-paygen-minios for more info about minios skips.
        if response.failure_reason == GenerationResponse.NOT_MINIOS_COMPATIBLE:
          presentation.step_text = 'not compatible with miniOS, skipping'
          continue
        errors.append(
            api.future_utils.create_custom_response(
                request, StepFailure(response.failure_reason),
                paygen_response.call_count))
      artifacts = get_paygen_response_artifacts(response)
      for artifact in artifacts:
        report_payload = api.paygen_testing.create_paygen_build_report_payload(
            request, artifact.remote_uri, artifact.version)
        if report_payload:
          payloads.append(report_payload)

      test_configs = api.paygen_testing.set_up_paygen_test_configs(
          request, artifacts)
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
      api.paygen_testing.schedule_au_tests(paygen_test_configs)


def initialize_directories(api: RecipeApi, properties: PaygenProperties):
  """Set up all the directories needed to do paygen.

  Args:
    api: api object to use.
    properties: recipe properties.
  """
  with api.step.nest('initialization') as presentation:
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

    # Pull config-internal separately. This repo has a huge history that we
    # can't delete (as it would break manifests). Therefore we want to clone
    # alone at depth=1.
    with api.step.nest(
        'clone config-internal from {} branch'.format(config_internal_branch)):
      api.git.clone(
          'https://chrome-internal.googlesource.com/chromeos/config-internal',
          branch=config_internal_branch, target_path=config_path, depth=1)

    # Create chroot, with retries!
    timeout = properties.init_sdk_timeout_secs or None

    @exponential_retry(
        retries=3,
        delay=datetime.timedelta(seconds=properties.sdk_retry_delay or 300))
    def _retry_chroot_init_wrapper() -> Optional[StepFailure]:
      try:
        api.cros_sdk.create_chroot(version=None, timeout_sec=timeout)
      except Exception as e:
        if "timeout" in str(e):
          presentation.step_text = 'SDK initialization timed out'
          presentation.status = api.step.FAILURE
          return StepFailure(presentation.step_text)
        raise e
      return None

    exception = _retry_chroot_init_wrapper()
    if exception:
      raise exception  # pylint: disable-msg=E0702


def get_paygen_response_artifacts(
    resp: GenerationResponse) -> List[GenerationResponse.VersionedArtifact]:
  # Since the call can hit older versions that may not have the required
  # field, create it from older fields if needed.
  if resp.versioned_artifacts:
    return resp.versioned_artifacts
  return [
      GenerationResponse.VersionedArtifact(
          local_path=resp.local_path,
          remote_uri=resp.remote_uri,
      )
  ]


def report_paygen_success_to_snoopy(api: RecipeApi,
                                    req: PaygenProperties.PaygenRequest,
                                    resp: GenerationResponse):
  for artifact in get_paygen_response_artifacts(resp):
    with api.failures.ignore_exceptions():
      abspath = api.path.join(req.generation_request.chroot.path,
                              artifact.local_path.lstrip('/'))
      file_hash = api.file.file_hash(abspath, test_data='deadbeef')
      api.bcid_reporter.report_gcs(file_hash, artifact.remote_uri)


# TODO(crbug.com/1157719): Improve testing mock data. There is a disconnect
# between the mock data and the Recipe logic. For example, a call to
# GeneratePayloads with no request still returns a successful response.
def GenTests(api: RecipeTestApi):

  yield api.test(
      'chroot-timeout',
      api.properties(PaygenProperties(init_sdk_timeout_secs=5)),
      api.step_data(
          'initialization.init sdk.call chromite.api.SdkService/Create.call build API script',
          times_out_after=10),
      api.post_check(post_process.StepFailure, 'initialization'),
      api.post_check(post_process.StepTextEquals, 'initialization',
                     'SDK initialization timed out'),
      api.post_check(post_process.DoesNotRun, 'doing paygen'),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'chroot-failure-no-timeout',
      api.properties(PaygenProperties(sdk_retry_delay=1)),
      api.step_data(
          'initialization.init sdk.call chromite.api.SdkService/Create.call build API script',
          retcode=1),
      api.step_data(
          'initialization.init sdk (2).call chromite.api.SdkService/Create.call build API script',
          retcode=1),
      api.step_data(
          'initialization.init sdk (3).call chromite.api.SdkService/Create.call build API script',
          retcode=1),
      api.post_check(post_process.StepFailure, 'initialization'),
      api.post_check(post_process.DoesNotRun, 'doing paygen'),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )

  def generate_payload_response(
      api: RecipeTestApi, is_success: bool = True,
      versioned_artifacts: List[Dict[str, Any]] = None,
      failure_reason: GenerationResponse.FailureReason = None, retcode: int = 0,
      retry: int = 0) -> TestData:
    suffix = '' if not retry else ' retry ({})'.format(retry)
    data = json.dumps(
        dict(success=is_success, versioned_artifacts=versioned_artifacts,
             failure_reason=failure_reason), sort_keys=True)
    return api.cros_build_api.set_api_return(
        parent_step_name='doing paygen.running paygen operations in parallel',
        step_name='making single payload{}'.format(suffix), data=data,
        retcode=retcode)

  # Here to support backwards compatibility on branches
  def generate_legacy_payload_response(
      api: RecipeTestApi, is_success: bool = True, local_path: str = '',
      remote_uri: str = '',
      failure_reason: GenerationResponse.FailureReason = None, retcode: int = 0,
      retry: int = 0) -> TestData:
    suffix = '' if not retry else ' retry ({})'.format(retry)
    data = json.dumps(
        dict(success=is_success, local_path=local_path, remote_uri=remote_uri,
             failure_reason=failure_reason), sort_keys=True)
    return api.cros_build_api.set_api_return(
        parent_step_name='doing paygen.running paygen operations in parallel',
        step_name='making single payload{}'.format(suffix), data=data,
        retcode=retcode)

  def StepTextEquals(check: Callable[[bool], bool], step_odict: Dict[str, Step],
                     step: str, expected: str):
    """Check that the step's text equals given value.

    Args:
      step: The step to check the step text of.
      expected: The expected text of the step.

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
                  generation_request=api.paygen_testing
                  .EXAMPLE_GEN_REQUEST_FULL_DLC[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ])
          ]), **{
              "$chromeos/cros_infra_config":
                  CrosInfraConfigProperties(release_tot_builds_snapshot=True)
          }),
      generate_payload_response(
          api,
          versioned_artifacts=[dict(local_path='/tmp/aohiwdadoi/delta.bin')]),
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
      'dryrun-legacy',
      api.buildbucket.generic_build(builder="staging-paygen", bucket='staging'),
      api.properties(
          PaygenProperties(requests=[
              dict(
                  generation_request=api.paygen_testing
                  .EXAMPLE_GEN_REQUEST_FULL_DLC[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ])
          ]), **{
              "$chromeos/cros_infra_config":
                  CrosInfraConfigProperties(release_tot_builds_snapshot=True)
          }),
      generate_legacy_payload_response(api,
                                       local_path='/tmp/aohiwdadoi/delta.bin'),
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
                  generation_request=api.paygen_testing
                  .EXAMPLE_GEN_REQUEST_FULL_DLC[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ]),
              dict(
                  generation_request=api.paygen_testing
                  .EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED[0],
                  autoupdate_test_configs=[
                      AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax'])
                  ])
          ])),
      generate_payload_response(
          api, versioned_artifacts=[
              dict(version=1, local_path='/tmp/aohiwdadoi/delta.bin',
                   remote_uri=full_payload_uri),
              dict(version=2, local_path='/tmp/aohiwdadoi/delta.bin',
                   remote_uri=f'{full_payload_uri}2')
          ]),
      api.step_data('doing paygen.gsutil cat {}.json'.format(full_payload_uri),
                    stdout=api.raw_io.output(payload_json_data)),
      api.step_data(
          'doing paygen.gsutil cat {}.json (2)'.format(full_payload_uri),
          stdout=api.raw_io.output(payload_json_data)),
      api.step_data('doing paygen.gsutil cat {}2.json'.format(full_payload_uri),
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
                      generation_request=api.paygen_testing
                      .EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                      autoupdate_test_configs=[
                          AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                               applicable_models=['woomax'])
                      ]),
                  dict(
                      generation_request=api.paygen_testing
                      .EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                      autoupdate_test_configs=[
                          AutoupdateTestConfig(delta_type=common_pb2.OMAHA,
                                               applicable_models=['woomax'])
                      ])
              ], max_concurrent_requests=1)),
      generate_payload_response(
          api,
          versioned_artifacts=[dict(local_path='/tmp/aohiwdadoi/delta.bin')]),
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
              dict(generation_request=api.paygen_testing
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
              dict(generation_request=api.paygen_testing
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
              dict(generation_request=api.paygen_testing
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
              dict(generation_request=api.paygen_testing
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
      api.gitiles.get_file(
          api.paygen_testing.TEST_TARGET_TEST_REQUIREMENTS_DATA),
      api.properties(
          PaygenProperties(requests=[
              dict(
                  generation_request=api.paygen_testing
                  .EXAMPLE_GEN_REQUESTS_DELTA_N2N[0], autoupdate_test_configs=[
                      AutoupdateTestConfig(src_version='123',
                                           src_channel='canary-channel',
                                           delta_type=common_pb2.OMAHA,
                                           applicable_models=['woomax']),
                      AutoupdateTestConfig(src_version='123',
                                           src_channel='canary-channel',
                                           delta_type=common_pb2.FSI,
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
      api.cros_storage.test_listing(
          'doing paygen.setting up paygen test config.discover gs artifacts (3).gsutil list',
          full_payload_uri,
      ),
      api.step_data('doing paygen.gsutil cat {}.json'.format(full_payload_uri),
                    stdout=api.raw_io.output(payload_json_data)),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.MustRun,
                     'testing paygen.buildbucket.schedule'),
      api.post_check(post_process.MustRun,
                     'testing paygen.buildbucket.schedule (2)'),
      # Checking for a third test request ensures we collapse by model,
      # since there are two woomax test requests.
      api.post_check(post_process.DoesNotRun,
                     'testing paygen.buildbucket.schedule (3)'),
      api.post_check(post_process.LogContains,
                     'testing paygen.buildbucket.schedule', 'request',
                     ['"key": "label-model",', '"value": "other"']),
      api.post_check(post_process.LogContains,
                     'testing paygen.buildbucket.schedule (2)', 'request',
                     ['"key": "label-model",', '"value": "woomax"']),
      api.post_check(post_process.StatusSuccess),
      # api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'mismatched-payload-and-testing-config',
      api.properties(
          PaygenProperties(requests=[
              dict(
                  generation_request=api.paygen_testing
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
                  generation_request=api.paygen_testing
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
