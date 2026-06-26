# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS payloads (AU deltas etc)."""

import copy
import datetime
import hashlib
import json
import urllib.parse
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import MessageToJson

import PB.chromiumos.common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.chromite.api.payload import (GenerationResponse, GenerationRequest,
                                     GenerateUnsignedPayloadRequest,
                                     GenerateUnsignedPayloadResponse,
                                     FinalizePayloadRequest, UnsignedPayload)
from PB.recipes.chromeos.paygen import PaygenProperties
from recipe_engine import post_process
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData


DEPS = [
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/bcid_verifier',
    'recipe_engine/step',
    'recipe_engine/time',
    'bot_cost',
    'bot_scaling',
    'cros_build_api',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'cros_ssci',
    'cros_storage',
    'easy',
    'failures',
    'future_utils',
    'gcloud',
    'git',
    'gitiles',
    'naming',
    'paygen_orchestration',
    'paygen_testing',
    'repo',
    'signing',
    'src_state',
    'test_util',
    'workspace_util',
]

PROPERTIES = PaygenProperties

# Number of total tries on individual paygen jobs to attempt.
_PAYGEN_TRY_COUNT = 2


def RunSteps(api: RecipeApi, properties: PaygenProperties):
  with api.bot_cost.build_cost_context():
    api.easy.log_parent_step()
    with api.failures.ignore_exceptions():
      api.bcid_reporter.report_stage('start')

    api.bot_scaling.drop_cpu_cores(min_cpus_left=2, max_drop_ratio=.75)

    with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
      with api.failures.ignore_exceptions():
        api.bcid_reporter.report_stage('fetch')

      DoRunSteps(api, properties)


def DoRunSteps(api: RecipeApi, properties: PaygenProperties):
  # Set up builder state.
  initialize_directories(api, properties)
  # Set up holder objects.
  payloads = []

  with api.step.nest('doing paygen') as presentation:
    with api.failures.ignore_exceptions():
      api.bcid_reporter.report_stage('compile')

    failed_paygen_input_artifact_verification = set()

    # Get max number of concurrent requests - None is number of cores.
    max_concurrent_requests = properties.max_concurrent_requests or api.bot_scaling.get_num_cores(
    )
    presentation.step_text = 'max number of concurrent requests: {}'.format(
        max_concurrent_requests)
    # Create a parallel runner with our max number of requests.
    paygen_parallel_runner = api.future_utils.create_parallel_runner(
        max_concurrent_requests)

    for req in properties.requests:
      # If a docker image is specified, need to pull it down before calling
      # the BAPI since the BAPI is hermetic.
      if req.generation_request.docker_image:
        # TODO(b/304336865): Remove once LUCI auth context is fixed.
        api.step('docker auth', [
            'gcloud',
            'auth',
            'configure-docker',
            'us-docker.pkg.dev',
        ])
        api.step('docker pull', [
            'docker',
            'pull',
            req.generation_request.docker_image,
        ])
        break

    # Iterate through every request.
    with api.cros_build_api.parallel_operations():
      with api.step.nest('running paygen operations in parallel') as pres:
        # Artifacts need to be placed within the chromiumos checkout so that
        # the BAPI can find them.
        artifact_result_path_base = api.cros_source.workspace_path.joinpath(
            'artifacts')

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

          payload_name = api.naming.get_generation_request_title(
              MessageToDict(req).get('generationRequest', {}))

          # Each paygen request should get its own result path dir so as to avoid
          # clobbering. Create that here as the field is not populated by the
          # orchestrator.
          # We hash the payload_name to get something unique and deterministic.
          # pylint is broken for hexdigest, see https://github.com/pylint-dev/pylint/issues/4039.
          payload_name_hash = hashlib.shake_128(  # pylint: disable=too-many-function-args
              payload_name.encode('utf-8')).hexdigest(15)
          artifact_result_path = api.path.join(artifact_result_path_base,
                                               payload_name_hash)

          api.file.ensure_directory('create artifact_result_path',
                                    artifact_result_path)
          result_path = common_pb2.ResultPath(
              path=common_pb2.Path(
                  path=str(artifact_result_path),
                  location=common_pb2.Path.OUTSIDE))
          req.generation_request.result_path.CopyFrom(result_path)

          # If split paygen is enabled, use the new GenerateUnsignedPayload
          # and FinalizePayload BAPI endpoints.
          if properties.use_split_paygen:
            unsigned_payload_req, finalize_req = split_generation_request(
                req.generation_request)
            resp = api.cros_build_api.PayloadService.GenerateUnsignedPayload(
                unsigned_payload_req,
                name='making single unsigned payload{}'.format(suffix),
                step_text=payload_name)
            if get_failure_reason(resp):
              return resp
            # Verify bcid provenance.
            failed_paygen_input_artifact_verification.update(
                download_and_verify_paygen_inputs(
                    api, resp.unsigned_payloads,
                    properties.paygen_input_provenance_verification_fatal))

            finalize_req.payloads.extend(resp.unsigned_payloads)
            return api.cros_build_api.PayloadService.FinalizePayload(
                finalize_req, name='finalizing single payload{}'.format(suffix),
                step_text=payload_name)

          # Otherwise, use the GeneratePayload BAPI endpoint.
          return api.cros_build_api.PayloadService.GeneratePayload(
              req.generation_request,
              name='making single payload{}'.format(suffix),
              step_text=payload_name)

        # Go through each request now and do paygen with our parallel runner.
        for request in properties.requests:
          pres.logs['request'] = MessageToJson(request)

          paygen_parallel_runner.run_function_async(
              do_a_paygen, request,
              success_handler=lambda resp, req=request, api=api:
              report_paygen_success_to_snoopy(api, resp, req.generation_request)
              if not get_failure_reason(resp) else None,
              try_count=_PAYGEN_TRY_COUNT)

      errors, total_retries = [], 0
      failure_reasons = []
      for paygen_response in paygen_parallel_runner.wait_for_and_get_responses(
      ):

        response = paygen_response.resp
        request = paygen_response.req

        total_retries += paygen_response.call_count - 1

        # If an exception was thrown, add it to errors and move on to the next
        # request.
        if paygen_response.errored:
          errors.append(paygen_response)
          continue

        failure_reason = get_failure_reason(response)
        if failure_reason:
          failure_reason_str = 'UNSPECIFIED'
          # Try converting from enum to string.
          try:
            failure_reason_str = type(response).FailureReason.Name(
                failure_reason)
          except:  #pylint: disable=bare-except
            pass
          failure_reasons.append({
              'payload':
                  api.naming.get_generation_request_title(
                      MessageToDict(request).get('generationRequest', {})),
              'failure_reason':
                  failure_reason_str
          })
          # See go/rubik-must-paygen-minios for more info about minios skips.
          if failure_reason in [
              GenerationResponse.NOT_MINIOS_COMPATIBLE,
              GenerationResponse.MINIOS_COUNT_MISMATCH
          ]:
            presentation.step_text = 'not compatible with miniOS, skipping'
            continue
          errors.append(
              api.future_utils.create_custom_response(
                  request, StepFailure(get_failure_reason(response)),
                  paygen_response.call_count))

        artifacts = get_paygen_response_artifacts(response)
        for artifact in artifacts:
          report_payload = api.paygen_testing.create_paygen_build_report_payload(
              request, artifact.remote_uri, artifact.version)
          if report_payload:
            payloads.append(report_payload)

    api.easy.set_properties_step(
        payloads=[MessageToDict(payload) for payload in payloads])
    api.easy.set_properties_step(paygen_retries=total_retries)
    api.easy.set_properties_step(failure_reasons=failure_reasons)
    api.easy.set_properties_step(
        **{
            'bcid': {
                'failed_payload_input_prov_verification':
                    list(sorted(failed_paygen_input_artifact_verification))
            }
        })

    if errors:
      failure_msg_lines = ['paygen failed with errors:']
      failure_msg_lines.extend([
          '{request} - {error}'.format(
              request=api.naming.get_generation_request_title(
                  MessageToDict(x.req).get('generationRequest', {})),
              error=x.resp) for x in errors
      ])
      failure_msg = api.failures.format_summary_markdown(failure_msg_lines)
      raise StepFailure(failure_msg)
  with api.failures.ignore_exceptions():
    api.bcid_reporter.report_stage('upload-complete')


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

    config_path = api.cros_source.workspace_path / 'src/config-internal'

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

    if api.src_state.gerrit_changes and api.cros_infra_config.is_staging:
      with api.step.nest('apply changes') as presentation:
        skipped_changes = []
        with api.context(cwd=api.cros_source.workspace_path):
          project_names = {p.name for p in api.repo.project_infos()}
          # We're _actually_ done manipulating the input source, so apply patch sets
          # if you can.
          for change in api.src_state.gerrit_changes:
            # If the change is not associated with a project that is checked out
            # (i.e. a project in the "paygen" manifest group), skip it.
            # See b/315019776 for context.
            if change.project not in project_names:
              skipped_changes.append(MessageToJson(change))
              continue
            api.workspace_util.checkout_change(change=change)
        if skipped_changes:
          presentation.logs['irrelevant changes'] = skipped_changes

    # Create chroot, with retries!
    timeout = properties.init_sdk_timeout_secs or None

    @api.time.exponential_retry(
        retries=2,
        delay=datetime.timedelta(seconds=properties.sdk_retry_delay or 300))
    def _retry_chroot_init_wrapper() -> Optional[StepFailure]:
      try:
        # NB: We don't update the SDK as the latest prebuilt should suffice.
        api.cros_sdk.create_chroot(timeout_sec=timeout)
      except Exception as e:
        if 'timeout' in str(e):
          presentation.step_text = 'SDK initialization timed out'
          presentation.status = api.step.FAILURE
          return StepFailure(presentation.step_text)
        raise e
      return None

    exception = _retry_chroot_init_wrapper()
    if exception:
      raise exception  # pylint: disable-msg=E0702

    # 120 predates SDK prebuilts, so update chroot.
    if config_internal_branch == 'release-R120-15662.B':
      api.cros_sdk.update_chroot(timeout_sec=24 * 60 * 60)


def split_generation_request(
    req: GenerationRequest
) -> Tuple[GenerateUnsignedPayloadRequest, FinalizePayloadRequest]:
  """Split a GenerationRequest into the corresponding split paygen requests.

  The FinalizePayloadRequest will be missing the `payload` field, that should
  be populated with the contents of the `unsigned_payloads` field in the
  GenerateUnsignedPayloadResponse.

  Args:
    req: The GenerationRequest.

  Returns:
    The equivalent GenerateUnsignedPayloadRequest and FinalizePayloadRequest
    requests.
  """
  image_params = {
      req.WhichOneof('src_image_oneof'):
          getattr(req, req.WhichOneof('src_image_oneof')),
      req.WhichOneof('tgt_image_oneof'):
          getattr(req, req.WhichOneof('tgt_image_oneof'))
  }

  unsigned_payload_request = GenerateUnsignedPayloadRequest(
      minios=req.minios,
      chroot=req.chroot,
      result_path=req.result_path,
      **image_params,
  )
  finalize_payload_request = FinalizePayloadRequest(
      chroot=req.chroot, minios=req.minios, dryrun=req.dryrun,
      result_path=req.result_path, keyset=req.keyset, verify=req.verify,
      bucket=req.bucket, use_local_signing=req.use_local_signing,
      docker_image=req.docker_image, **image_params)
  return unsigned_payload_request, finalize_payload_request


def get_failure_reason(
    resp: Union[GenerationResponse, GenerateUnsignedPayloadResponse,
                FinalizePayloadRequest]
) -> int:
  """Get the failure reason from the given response, if any."""
  # FinalizePayloadRequest doesn't have a 'failure_reason' field, default to
  # 0 / UNSPECIFIED.
  return MessageToDict(resp,
                       use_integers_for_enums=True).get('failureReason', 0)


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


def report_paygen_success_to_snoopy(api: RecipeApi, resp: GenerationResponse,
                                    req: GenerationRequest):
  for artifact in get_paygen_response_artifacts(resp):
    with api.failures.ignore_exceptions():
      if artifact.file_path.location is common_pb2.Path.Location.OUTSIDE:
        abspath = artifact.file_path.path
        file_hash = api.file.file_hash(abspath, test_data='deadbeef')
        # Only generate BCID attestation when local signing is used.
        if req.use_local_signing:
          with api.step.nest(f'generate and upload payload sbom: {abspath}'):
            parsed_uri = urllib.parse.urlparse(artifact.remote_uri)
            gs_bucket = parsed_uri.netloc
            gs_path = parsed_uri.path.lstrip('/')
            local_spdx_path = api.path.mkdtemp(
                'cros_ssci_') / 'payload.spdx.json'
            api.cros_ssci.generate_payload_sbom(req, local_spdx_path)
            uploaded_sbom = api.cros_ssci.upload_sbom(
                local_spdx_path, gs_bucket=gs_bucket,
                gs_path=f'{gs_path}.spdx.json')

          # Report GCS attestation.
          api.bcid_reporter.report_sbom(uploaded_sbom.digest,
                                        uploaded_sbom.gs_url,
                                        sbom_subjects=[file_hash])
          api.bcid_reporter.report_gcs(file_hash, artifact.remote_uri)
      else:
        raise api.step.StepFailure(
            f'Artifact file_path must have Path.Location.OUTSIDE, file_path: {artifact.file_path}'
        )


def download_and_verify_paygen_inputs(
    api: RecipeApi, unsigned_payloads: List[UnsignedPayload],
    paygen_input_provenance_verification_fatal: bool = False):
  """Download attestations for inputs to paygen and call BCID verifier.

  Args:
    api: api object to use.
    unsigned_payloads: list of unsigned payloads, including their inputs.
    paygen_input_provenance_verification_fatal: Whether BCID verification of paygen inputs is fatal.

  Returns:
    Set of artifacts which failed download or verification.
  """
  failed_artifact_verification = set()
  for unsigned_payload in unsigned_payloads:

    # list of tuples (local_path, remote_path)
    artifacts_to_verify = []

    # Download attestations for input artifacts.
    for payload_input in unsigned_payload.payload_inputs:
      artifact_path = payload_input.path.path
      artifact_name = api.path.basename(artifact_path)
      attestation_path_remote = api.signing.get_bcid_attestation_pattern.format(
          artifact=payload_input.gs_path)
      attestation_path_local = api.signing.get_bcid_attestation_pattern.format(
          artifact=artifact_path)
      with api.step.nest(f'download attestation for {artifact_name}') as pres:
        try:
          api.gcloud.download_file(attestation_path_remote,
                                   attestation_path_local)
          artifacts_to_verify.append(
              (artifact_path, payload_input.gs_path.replace("gs://", "")))
        except StepFailure as step_failure:
          pres.step_summary_text = 'attestation download failed'
          failed_artifact_verification.add(payload_input.gs_path)
          if paygen_input_provenance_verification_fatal:
            pres.status = api.step.FAILURE
            raise step_failure
          # No attestation, cannot continue with verification
          continue

      failed_verification = api.signing.verify_bcid_attestations_for_artifacts(
          artifacts_to_verify, True, paygen_input_provenance_verification_fatal,
          resource_prefix="paygen")
      if failed_verification:
        failed_artifact_verification.add(payload_input.gs_path)
    with api.step.nest('clean up payload input archives'):
      for payload_input in unsigned_payload.payload_inputs:
        # If reporting inputs, delete archives which have been extracted.
        if payload_input.is_archive:
          api.file.remove(f'removing input archive {payload_input.path.path}',
                          payload_input.path.path)

  return failed_artifact_verification


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
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
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
      api.post_check(post_process.StepException, 'initialization'),
      api.post_check(post_process.DoesNotRun, 'doing paygen'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  def generate_payload_response(
      api: RecipeTestApi, is_success: bool = True,
      versioned_artifacts: List[Dict[str, Any]] = None,
      failure_reason: GenerationResponse.FailureReason = None, retcode: int = 0,
      retry: int = 0, iteration: int = 1) -> TestData:
    suffix = '' if not retry else ' retry ({})'.format(retry)
    data = json.dumps(
        {
            'success': is_success,
            'versioned_artifacts': versioned_artifacts,
            'failure_reason': failure_reason,
        }, sort_keys=True)
    return api.cros_build_api.set_api_return(
        parent_step_name='doing paygen.running paygen operations in parallel',
        step_name='making single payload{}'.format(suffix), data=data,
        retcode=retcode, iteration=iteration)

  # TODO(b/296444046): Remove when older branches age out.
  # Here to support backwards compatibility on branches
  def generate_legacy_payload_response(
      api: RecipeTestApi, is_success: bool = True, local_path: str = '',
      remote_uri: str = '',
      failure_reason: GenerationResponse.FailureReason = None, retcode: int = 0,
      retry: int = 0) -> TestData:
    suffix = '' if not retry else ' retry ({})'.format(retry)
    data = json.dumps(
        {
            'success': is_success,
            'local_path': local_path,
            'remote_uri': remote_uri,
            'failure_reason': failure_reason,
        }, sort_keys=True)
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
  payload_json_data = '''{
  "appid": "appid",
  "metadata_signature": "signature",
  "metadata_size": 1337,
  "size": 1234,
  "source_version": "1.2.3",
  "target_version": "4.5.6",
  "sha256_hex": "deadbeef",
  "is_delta": true
}'''

  # Commonly used payload response test data for a versioned artifact outside the chroot.
  delta_outside_chroot = {
      'local_path': '/tmp/aohiwdadoi/delta.bin',
      'file_path': {
          'path': '/path/to/cros_chroot/out/tmp/delta.bin',
          'location': 2
      }
  }

  delta_outside_chroot_with_uri = {
      'local_path': '/tmp/aohiwdadoi/delta.bin',
      'file_path': {
          'path': '/path/to/cros_chroot/out/tmp/delta.bin',
          'location': 2
      },
      'remote_uri': full_payload_uri,
  }
  yield api.test(
      'dryrun',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.properties(
          PaygenProperties(requests=[{
              'generation_request':
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
          }])),
      generate_payload_response(api,
                                versioned_artifacts=[delta_outside_chroot]),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.MustRun,
                     'initialization.clone config-internal from main branch'),
      api.post_check(
          post_process.DoesNotRun,
          'doing paygen.running paygen operations in parallel.snoop: report_gcs'
      ),
      # api.post_process(post_process.DropExpectation),
  )

  def test_builder(**kwargs) -> TestData:
    """Generate a test build."""
    kwargs.setdefault('builder', 'staging-paygen-mpa')
    kwargs.setdefault('bucket', 'staging')
    kwargs.setdefault('cq', 'true')
    kwargs.setdefault('git_repo', api.src_state.internal_manifest.url)
    return api.test_util.test_build(**kwargs).build

  changes = [
      GerritChange(change=123, project='chromiumos/third_party/kernel',
                   host='chromium-review.googlesource.com', patchset=1),
      GerritChange(change=234, project='chromiumos/non-paygen-change',
                   host='chromium-review.googlesource.com', patchset=1),
  ]

  yield api.test(
      'dryrun-with-changes',
      test_builder(gerrit_changes=changes),
      api.properties(
          PaygenProperties(requests=[
              {
                  'generation_request':
                      api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              },
          ])),
      api.step_data(
          'initialization.apply changes.repo forall',
          stdout=api.raw_io.output_text(
              'chromiumos/third_party/kernel|src/third_party/kernel|cros|refs/heads/main|refs/heads/main'
          )),
      generate_payload_response(api,
                                versioned_artifacts=[delta_outside_chroot]),
      api.post_check(post_process.LogContains, 'initialization.apply changes',
                     'irrelevant changes', ['234']),
      api.post_check(post_process.MustRun,
                     'initialization.apply changes.checkout gerrit change'),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.MustRun,
                     'initialization.clone config-internal from main branch'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'dryrun-legacy',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.properties(
          PaygenProperties(requests=[
              {
                  'generation_request':
                      api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              },
          ])),
      generate_legacy_payload_response(api,
                                       local_path='/tmp/aohiwdadoi/delta.bin'),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.MustRun,
                     'initialization.clone config-internal from main branch'),
      # api.post_process(post_process.DropExpectation),
  )

  EXAMPLE_GEN_REQUEST_FULL_UNSIGNED = GenerationRequest(
      full_update=True,
      tgt_unsigned_image=api.paygen_orchestration.UNSIGNED_TGT,
      bucket='b',
      verify=True,
      dryrun=True,
      chroot=api.cros_sdk.chroot(),
  )

  yield api.test(
      'multiple-dryruns',
      api.properties(
          PaygenProperties(requests=[
              {
                  'generation_request':
                      api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
              },
              {
                  'generation_request': EXAMPLE_GEN_REQUEST_FULL_UNSIGNED,
              },
          ])),
      generate_payload_response(
          api, versioned_artifacts=[
              {
                  'version': 1,
                  'local_path': '/tmp/aohiwdadoi/delta.bin',
                  'file_path': {
                      'path': '/path/to/cros_chroot/out/tmp/delta.bin',
                      'location': 2
                  },
                  'remote_uri': full_payload_uri,
              },
              {
                  'version': 2,
                  'local_path': '/tmp/aohiwdadoi/delta.bin',
                  'file_path': {
                      'path': '/path/to/cros_chroot/out/tmp/delta.bin',
                      'location': 2
                  },
                  'remote_uri': f'{full_payload_uri}2',
              },
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
      # api.post_process(post_process.DropExpectation),
  )

  # Commonly used payload request test data for DLC delta with local signing.
  delta_dlc_local_signing_req = GenerationRequest(
      full_update=True,
      tgt_dlc_image=api.paygen_orchestration.DLC_TGT,
      bucket='b',
      verify=True,
      dryrun=True,
      use_local_signing=True,
      docker_image='us-docker.pkg.dev/chromeos-release-bot/signing/foo',
  )

  yield api.test(
      'local-signing',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.properties(
          PaygenProperties(requests=[{
              'generation_request': delta_dlc_local_signing_req
          }]),
      ),
      generate_payload_response(
          api, versioned_artifacts=[delta_outside_chroot_with_uri]),
      api.step_data('doing paygen.gsutil cat {}.json'.format(full_payload_uri),
                    stdout=api.raw_io.output(payload_json_data)),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.StepCommandContains,
                     'doing paygen.docker pull', [
                         'docker', 'pull',
                         'us-docker.pkg.dev/chromeos-release-bot/signing/foo'
                     ]),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.snoop: report_sbom'
      ),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.snoop: report_gcs'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'multiple-runs-no-concurrency',
      api.properties(
          PaygenProperties(
              requests=[
                  {
                      'generation_request':
                          api.paygen_orchestration
                          .EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                  },
                  {
                      'generation_request':
                          api.paygen_orchestration
                          .EXAMPLE_GEN_REQUEST_FULL_DLC[0],
                  },
              ], max_concurrent_requests=1)),
      generate_payload_response(api,
                                versioned_artifacts=[delta_outside_chroot]),
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
      # api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'failed-paygen',
      api.properties(
          PaygenProperties(requests=[{
              'generation_request':
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0]
          }])),
      # Our current set of failure reasons are all non-fatal minios exceptions,
      # pass bogus non-zero failure_reason for coverage.
      generate_payload_response(api, is_success=False, retcode=2,
                                failure_reason=3),
      api.post_check(post_process.StepFailure, 'doing paygen'),
      api.post_check(post_process.PropertyEquals, 'failure_reasons', [{
          'failure_reason': 'UNSPECIFIED',
          'payload': 'DLC (termina-dlc) stable-channel | Full (13425.90.0)'
      }]),
      # api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'failed-paygen-exception',
      api.properties(
          PaygenProperties(requests=[{
              'generation_request':
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0]
          }])),
      generate_payload_response(api, is_success=False, retcode=3,
                                failure_reason=2),
      generate_payload_response(api, is_success=False, retcode=3,
                                failure_reason=2, retry=1),
      api.post_check(post_process.StepFailure, 'doing paygen'),
      # api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  req_cnt = 10
  # Deep copy and mutate to make the title very long, so we need fewer requests
  # to trigger the summary truncation logic.
  long_req = copy.deepcopy(
      api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0])
  long_req.tgt_dlc_image.dlc_id = 'a' * 500
  test_data = api.properties(
      PaygenProperties(requests=[{
          'generation_request': long_req
      }] * req_cnt))
  for i in range(1, req_cnt + 1):
    test_data += generate_payload_response(api, is_success=False, retcode=3,
                                           failure_reason=2, iteration=i)
    test_data += generate_payload_response(api, is_success=False, retcode=3,
                                           failure_reason=2, retry=1,
                                           iteration=i)
  yield api.test(
      'failed-paygen-exception-truncated',
      test_data,
      # Check that the failure message is truncated.
      api.post_process(post_process.SummaryMarkdownRE, r'\n\n\.\.\.$'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'failed-minios',
      api.properties(
          PaygenProperties(requests=[{
              'generation_request':
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0]
          }])),
      generate_payload_response(
          api, is_success=False, retcode=2,
          failure_reason=GenerationResponse.NOT_MINIOS_COMPATIBLE),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.PropertyEquals, 'failure_reasons', [{
          'failure_reason': 'NOT_MINIOS_COMPATIBLE',
          'payload': 'DLC (termina-dlc) stable-channel | Full (13425.90.0)'
      }]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'failed-minios-partition-mismatch',
      api.properties(
          PaygenProperties(requests=[{
              'generation_request':
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0]
          }])),
      generate_payload_response(
          api, is_success=False, retcode=2,
          failure_reason=GenerationResponse.MINIOS_COUNT_MISMATCH),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.PropertyEquals, 'failure_reasons', [{
          'failure_reason': 'MINIOS_COUNT_MISMATCH',
          'payload': 'DLC (termina-dlc) stable-channel | Full (13425.90.0)'
      }]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'fail-attest-path-inside-chroot',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.properties(
          PaygenProperties(requests=[{
              'generation_request':
                  api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
          }])),
      generate_payload_response(
          api, versioned_artifacts=[{
              'local_path': '/tmp/aohiwdadoi/delta.bin',
              'file_path': {
                  'path': '/path/to/cros_chroot/out/tmp/delta.bin',
                  'location': 1
              }
          }]),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.ignored exception'
      ),
  )

  def generate_split_payload_response(
      api: RecipeTestApi, payloads: List[Dict[str, Any]] = None,
      versioned_artifacts: List[Dict[str, Any]] = None,
      failure_reason: GenerateUnsignedPayloadResponse.FailureReason = None,
      retcode: int = 0, retry: int = 0,
      fatal_bcid_failure: bool = False) -> TestData:
    suffix = '' if not retry else ' retry ({})'.format(retry)

    unsigned_payload_data = json.dumps({
        'failure_reason': failure_reason,
        'unsigned_payloads': payloads,
    })
    finalize_payload_data = json.dumps(
        {
            'versioned_artifacts': versioned_artifacts,
        }, sort_keys=True)
    ret = [
        api.cros_build_api.set_api_return(
            parent_step_name='doing paygen.running paygen operations in parallel',
            step_name='making single unsigned payload{}'.format(suffix),
            data=unsigned_payload_data, retcode=retcode),
    ]
    # Only add data for the FinalizePayload call if we don't have a failure
    # reason or fatal BCID failure -- if we do, we'll exit before making this call.
    if not failure_reason and not fatal_bcid_failure:
      ret.append(
          api.cros_build_api.set_api_return(
              parent_step_name='doing paygen.running paygen operations in parallel',
              step_name='finalizing single payload{}'.format(suffix),
              data=finalize_payload_data, retcode=retcode))
    return ret

  # TODO(b/299105459): Move all tests to use split paygen flow / test data
  # once the property is removed.

  # Commonly used payload request test data for DLC delta.
  delta_dlc_req = GenerationRequest(
      full_update=True,
      tgt_dlc_image=api.paygen_orchestration.DLC_TGT,
      bucket='b',
      verify=True,
      dryrun=True,
  )
  # Commonly used payload response test data for a delta.
  delta_payload_resp = {
      'version':
          1,
      'payload_file_path': {
          'path': '/tmp/aohiwdadoi/delta.bin',
          'location': 1,
      },
      'partition_names': ['foo-root', 'foo-kernel'],
      'tgt_partitions': [{
          'path': '/tmp/aohiwdadoi/tgt_root.bin',
          'location': 1,
      }, {
          'path': '/tmp/aohiwdadoi/tgt_kernel.bin',
          'location': 1,
      }],
  }

  yield api.test(
      'split-paygen',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.properties(
          PaygenProperties(requests=[{
              'generation_request': delta_dlc_req
          }], use_split_paygen=True),
      ),
      *generate_split_payload_response(
          api, payloads=[delta_payload_resp],
          versioned_artifacts=[delta_outside_chroot]),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'split-paygen-failed-minios-partition-mismatch',
      api.properties(
          PaygenProperties(
              requests=[{
                  'generation_request':
                      api.paygen_orchestration.EXAMPLE_GEN_REQUEST_FULL_DLC[0]
              }], use_split_paygen=True)),
      *generate_split_payload_response(
          api, retcode=2,
          failure_reason=GenerationResponse.MINIOS_COUNT_MISMATCH),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.PropertyEquals, 'failure_reasons', [{
          'failure_reason': 'MINIOS_COUNT_MISMATCH',
          'payload': 'DLC (termina-dlc) stable-channel | Full (13425.90.0)'
      }]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'split-paygen-local-signing',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.properties(
          PaygenProperties(
              requests=[{
                  'generation_request': delta_dlc_local_signing_req
              }], use_split_paygen=True),
      ),
      *generate_split_payload_response(
          api, payloads=[delta_payload_resp],
          versioned_artifacts=[delta_outside_chroot]),
      api.post_check(post_process.MustRun, 'doing paygen'),
      api.post_check(post_process.StepCommandContains,
                     'doing paygen.docker pull', [
                         'docker', 'pull',
                         'us-docker.pkg.dev/chromeos-release-bot/signing/foo'
                     ]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.cros_source.test(
      '120-update-chroot',
      'release-R120-15662.B',
      api.post_check(post_process.MustRun, 'initialization.update sdk'),
      api.post_process(post_process.DropExpectation),
  )

  # Commonly used payload response test data for a delta with inputs.
  delta_payload_resp_with_inputs = copy.deepcopy(delta_payload_resp)
  delta_payload_resp_with_inputs['payload_inputs'] = [{
      'gs_path': 'gs://path-to-input',
      'path': {
          'path': '[CLEANUP]/local/path/to/input'
      },
      'is_archive': False
  }, {
      'gs_path': 'gs://path-to-input-archive',
      'path': {
          'path': '[CLEANUP]/local/path/to/input/archive'
      },
      'is_archive': True
  }]
  yield api.test(
      'paygen-inputs',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.path.files_exist(
          api.path.cleanup_dir / 'local/path/to/input.intoto.jsonl',
          api.path.cleanup_dir / 'local/path/to/input/archive.intoto.jsonl'),
      api.properties(
          PaygenProperties(
              requests=[{
                  'generation_request': delta_dlc_local_signing_req
              }], use_split_paygen=True),
      ),
      *generate_split_payload_response(
          api, payloads=[delta_payload_resp_with_inputs],
          versioned_artifacts=[delta_outside_chroot]),
      api.post_check(
          post_process.DoesNotRun,
          'doing paygen.running paygen operations in parallel.clean up payload input archives.removing input archive [CLEANUP]/local/path/to/input'
      ),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.clean up payload input archives.removing input archive [CLEANUP]/local/path/to/input/archive'
      ),
      api.post_check(post_process.StepCommandContains,
                     'doing paygen.docker pull', [
                         'docker', 'pull',
                         'us-docker.pkg.dev/chromeos-release-bot/signing/foo'
                     ]),
      api.post_check(
          post_process.StepCommandContains,
          'doing paygen.running paygen operations in parallel.download attestation for input.download GS file',
          [
              "gcloud",
              "storage",
              "cp",
              "gs://path-to-input.intoto.jsonl",
              "[CLEANUP]/local/path/to/input.intoto.jsonl",
          ],
      ),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.verify provenance.verifying provenance for input.bcid_verifier: verify provenance'
      ),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.snoop: report_gcs'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'paygen-inputs-attestation-download-verification-fails-nonfatal',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.path.files_exist(
          api.path.cleanup_dir / 'local/path/to/input.intoto.jsonl',
          api.path.cleanup_dir / 'local/path/to/input/archive.intoto.jsonl'),
      api.properties(
          PaygenProperties(
              requests=[{
                  'generation_request': delta_dlc_local_signing_req
              }], use_split_paygen=True,
              paygen_input_provenance_verification_fatal=False),
      ),
      *generate_split_payload_response(
          api, payloads=[delta_payload_resp_with_inputs],
          versioned_artifacts=[delta_outside_chroot]),
      # All retries for downloading "input" attestation fail.
      api.step_data(
          'doing paygen.running paygen operations in parallel.download attestation for input.download GS file',
          retcode=1),
      api.step_data(
          'doing paygen.running paygen operations in parallel.download attestation for input.download GS file (2)',
          retcode=1),
      api.step_data(
          'doing paygen.running paygen operations in parallel.download attestation for input.download GS file (3)',
          retcode=1),
      api.post_check(
          post_process.DoesNotRun,
          'doing paygen.running paygen operations in parallel.verify provenance.verifying provenance for input'
      ),
      # Verification of "archive" attestation fails.
      api.step_data(
          'doing paygen.running paygen operations in parallel.verify provenance.verifying provenance for archive.bcid_verifier: verify provenance',
          retcode=1),
      # Output property captures failures, but build succeeds.
      api.post_check(
          post_process.PropertyEquals, 'bcid', {
              "failed_payload_input_prov_verification":
                  ["gs://path-to-input", "gs://path-to-input-archive"]
          }),
      api.post_check(
          post_process.MustRun,
          'doing paygen.running paygen operations in parallel.finalizing single payload'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'paygen-inputs-attestation-download-fails-fatal',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.path.files_exist(
          api.path.cleanup_dir / 'local/path/to/input.intoto.jsonl',
          api.path.cleanup_dir / 'local/path/to/input/archive.intoto.jsonl'),
      api.properties(
          PaygenProperties(
              requests=[{
                  'generation_request': delta_dlc_local_signing_req
              }], use_split_paygen=True,
              paygen_input_provenance_verification_fatal=True),
      ),
      # Both tries will fail BCID verification.
      *generate_split_payload_response(
          api, payloads=[delta_payload_resp_with_inputs],
          versioned_artifacts=[delta_outside_chroot], fatal_bcid_failure=True),
      *generate_split_payload_response(
          api, payloads=[delta_payload_resp_with_inputs],
          versioned_artifacts=[delta_outside_chroot], fatal_bcid_failure=True,
          retry=1),
      # All retries for downloading "input" attestation fail.
      api.step_data(
          'doing paygen.running paygen operations in parallel.download attestation for input.download GS file',
          retcode=1),
      api.step_data(
          'doing paygen.running paygen operations in parallel.download attestation for input.download GS file (2)',
          retcode=1),
      api.step_data(
          'doing paygen.running paygen operations in parallel.download attestation for input.download GS file (3)',
          retcode=1),
      api.step_data(
          'doing paygen.running paygen operations in parallel.download attestation for input (2).download GS file',
          retcode=1),
      api.step_data(
          'doing paygen.running paygen operations in parallel.download attestation for input (2).download GS file (2)',
          retcode=1),
      api.step_data(
          'doing paygen.running paygen operations in parallel.download attestation for input (2).download GS file (3)',
          retcode=1),
      # Payload is not finalized and signed, and the build fails.
      api.post_check(
          post_process.DoesNotRun,
          'doing paygen.running paygen operations in parallel.verify provenance.verifying provenance for input'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'doing paygen.running paygen operations in parallel.finalizing single payload'
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'paygen-inputs-attestation-verification-fails-fatal',
      api.buildbucket.generic_build(builder='staging-paygen-mpa',
                                    bucket='staging'),
      api.path.files_exist(
          api.path.cleanup_dir / 'local/path/to/input.intoto.jsonl',
          api.path.cleanup_dir / 'local/path/to/input/archive.intoto.jsonl'),
      api.properties(
          PaygenProperties(
              requests=[{
                  'generation_request': delta_dlc_local_signing_req
              }], use_split_paygen=True,
              paygen_input_provenance_verification_fatal=True),
      ),
      # Both tries will fail BCID verification.
      *generate_split_payload_response(
          api, payloads=[delta_payload_resp_with_inputs],
          versioned_artifacts=[delta_outside_chroot], fatal_bcid_failure=True),
      *generate_split_payload_response(
          api, payloads=[delta_payload_resp_with_inputs],
          versioned_artifacts=[delta_outside_chroot], fatal_bcid_failure=True,
          retry=1),
      # All retries for "input" verification fail.
      api.step_data(
          'doing paygen.running paygen operations in parallel.verify provenance.verifying provenance for input.bcid_verifier: verify provenance',
          retcode=1),
      api.step_data(
          'doing paygen.running paygen operations in parallel.verify provenance (2).verifying provenance for input.bcid_verifier: verify provenance',
          retcode=1),
      # Payload is not finalized and signed, and the build fails.
      api.post_check(
          post_process.DoesNotRun,
          'doing paygen.running paygen operations in parallel.finalizing single payload'
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
