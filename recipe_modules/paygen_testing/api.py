# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

"""API for working with Paygen testing. Used by paygen.py."""
import collections
import json
from datetime import timedelta
from os import path
from typing import Dict, List, Optional, Tuple

from RECIPE_MODULES.recipe_engine.time.api import exponential_retry
from RECIPE_MODULES.chromeos.cros_storage.api import FullPayload
from RECIPE_MODULES.chromeos.cros_storage.api import Payload
from google.protobuf import duration_pb2
from google.protobuf.json_format import MessageToDict

import PB.chromiumos.common as common_pb2
from PB.chromite.api import test_metadata
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import GenerationResponse
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.build_report import URI
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.recipe_modules.chromeos.paygen_testing.paygen_testing import PaygenTestingProperties
from PB.recipe_modules.chromeos.paygen_testing.paygen_testing import TestRequestOpts
from PB.recipes.chromeos.paygen import PaygenProperties
from PB.test_platform.request import Request
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

QS_ACCOUNT = 'legacypool-bvt'
LABEL_POOL = 'quota'


class PaygenTestConfig():
  """A single test configuration.

  Stores and generates arguments for running autoupdate_EndToEndTest.

  Paygen Autotest documentation:
  go/cros-au-testplan#heading=h.9pokikke2eh

  autoupdate_EndToEndTest control file:
  http://cs/chromeos_public/src/third_party/autotest/files/server/site_tests/
    autoupdate_EndToEndTest/control

  autoupdate_EndToEndTest file:
  https://source.corp.google.com/chromeos_public/src/third_party/autotest/files/
    server/site_tests/autoupdate_EndToEndTest/autoupdate_EndToEndTest.py

  Example cros_test_platform build which enumerates the tests:
  https://ci.chromium.org/b/8865978197367928464

  Example test_runner build which invokes the autoupdate_EndToEndTest with the
  appropriate test arguments:
  https://ci.chromium.org/b/8865978162264605344
  """

  _AUTOTEST_DEFAULT_TIMEOUT = duration_pb2.Duration(seconds=7 * 60 * 60)
  _AUTOTEST_DEFAULT_MAX_RETRIES = 5
  _AUTOTEST_TEST_NAME = 'autoupdate_EndToEndTest'
  _PAYGEN_AU_SUITE_TEMPLATE = 'paygen_au_%s'

  _UNIQUE_NAME_SUFFIX_TEMPLATE = (
      '%(suite_name)s_%(update_type)s_%(src_version)s_%(delta_type)s')
  _DISPLAY_NAME_TEMPLATE = (
      '%(build_target_name)s-release/%(tgt_archive_basename)s/%(suite_name)s/'
      '%(test_name)s_%(unique_name_suffix)s')
  # test_platform.software_dependency.chromeos_build
  # (e.g. reef-release/R77-12345.0.0)
  _CHROMEOS_BUILD_NAME_TEMPLATE = (
      '%(build_target_name)s-release/%(tgt_archive_basename)s')
  _REQUEST_TAG_TEMPLATE = '%(chromeos_build_name)s-%(tgt_channel)s-%(update_type)s'
  _REQUEST_WITH_MODEL_TAG_TEMPLATE = (
      '%(chromeos_build_name)s-%(tgt_channel)s-%(update_type)s-%(model)s')

  def __init__(self, test_build_target: str, build_target_name: str,
               tgt_channel: str, tgt_version: str, tgt_payload_uri: str,
               tgt_archive_uri: str, tgt_container_metadata_uri: str,
               is_delta_update: bool, delta_type: common_pb2.DeltaType,
               src_version: str, src_payload_uri: str, src_artifact_uri: str,
               applicable_models: List[str] = None, critical: bool = False,
               quota_scheduler_account: str = QS_ACCOUNT,
               quota_scheduler_label_pool: str = LABEL_POOL):
    """Initialize a test configuration.

    Args:
      test_build_target: The name of the physical board being tested
        (e.g. auron_paine), must be matched for scheduling in the lab.
      build_target_name: The name of the build target (e.g.
        kevin or kevin-kernelnext).
      tgt_channel: The channel of the target payload
        (e.g. 'canary-channel').
      tgt_version: The target image version (e.g. '13373.0.0').
      tgt_payload_uri: The target payload URI.
      tgt_archive_uri: The location of target build archive artifacts.
      tgt_container_metadata_uri: The location of target container metadata.
      is_delta_update: Whether this is a delta update test.
      delta_type: The type of update to do with the payload.
      src_version: The source image version (e.g. '13373.0.0').
      src_payload_uri: The source payload URI.
      src_artifact_uri: The location of source build artifacts.
      applicable_models: A list of models that this config should
        run against. None indicates it can run on any build_target.
      critical: Whether the test should be run as critical.
    """
    self._test_build_target = test_build_target
    self._build_target_name = build_target_name
    self._tgt_channel = tgt_channel
    self._tgt_version = tgt_version
    self._tgt_payload_uri = tgt_payload_uri
    self._tgt_archive_uri = tgt_archive_uri
    self._tgt_container_metadata_uri = tgt_container_metadata_uri

    self._src_version = src_version
    self._src_payload_uri = src_payload_uri
    self._src_artifact_uri = src_artifact_uri

    self._tgt_archive_basename = path.basename(self._tgt_archive_uri)
    self._update_type = 'delta' if is_delta_update else 'full'
    self._delta_type = delta_type
    self._applicable_models = applicable_models

    self._chromeos_build_name = self._CHROMEOS_BUILD_NAME_TEMPLATE % {
        'build_target_name': self._build_target_name,
        'tgt_archive_basename': self._tgt_archive_basename
    }

    self._suite_name = (
        self._PAYGEN_AU_SUITE_TEMPLATE % self._tgt_channel.split('-')[0])
    self._unique_name_suffix = self._UNIQUE_NAME_SUFFIX_TEMPLATE % {
        'suite_name': self._suite_name,
        'update_type': self._update_type,
        'src_version': self._src_version,
        'delta_type': common_pb2.DeltaType.Name(self._delta_type).lower()
    }
    self._display_name = self._DISPLAY_NAME_TEMPLATE % {
        'build_target_name': self._build_target_name,
        'tgt_archive_basename': self._tgt_archive_basename,
        'suite_name': self._suite_name,
        'test_name': self._AUTOTEST_TEST_NAME,
        'unique_name_suffix': self._unique_name_suffix,
    }

    self._quota_scheduler_account = quota_scheduler_account
    self._quota_scheduler_label_pool = quota_scheduler_label_pool

    self._critical = critical

  @property
  def build_target_name(self) -> str:
    return self._build_target_name

  @property
  def test_build_target(self) -> str:
    return self._test_build_target

  @property
  def critical(self) -> bool:
    return self._critical

  def _get_test_plan(self) -> Request.TestPlan:
    """A test_platform TestPlan proto with the enumerated test request."""
    autotest_invocation = Request.Enumeration.AutotestInvocation(
        test=test_metadata.AutotestTest(
            name=self._AUTOTEST_TEST_NAME, allow_retries=True, max_retries=1,
            execution_environment=(
                test_metadata.AutotestTest.EXECUTION_ENVIRONMENT_SERVER)),
        test_args=self._get_test_args(),
        display_name=self._display_name,
    )
    return Request.TestPlan(
        enumeration=Request.Enumeration(
            autotest_invocations=[autotest_invocation]))

  def _get_test_args(self) -> str:
    """Test arguments with which to invoke the autotest control file."""
    template = '%s=%s'
    arg_values = [('name', self._suite_name),
                  ('update_type', self._update_type),
                  ('source_release', self._src_version),
                  ('target_release', self._tgt_version),
                  ('target_payload_uri', self._tgt_payload_uri),
                  ('SUITE', self._suite_name),
                  ('source_payload_uri', self._src_payload_uri),
                  ('source_archive_uri', self._src_artifact_uri),
                  ('payload_type', common_pb2.DeltaType.Name(self._delta_type))]

    return ' '.join(template % (key, val) for key, val in arg_values)

  def to_ctp_tagged_requests(self, request_opts: TestRequestOpts = None
                            ) -> Dict[str, Dict]:
    """Turn self into a dict of tagged test_platform.Requests.

    Creates one request per testable model or one request with no model
    specified if self._applicable_models and models is None.

    Args:
      request_opts: Overrides for the test_platform.Request.

    Returns:
       A dictionary of string to test_platform.Request objects.
    """
    if not self._applicable_models:
      return self._create_tagged_request(request_opts=request_opts)

    tagged_requests = {}
    for model in self._applicable_models:
      tagged_requests.update(
          self._create_tagged_request(model=model, request_opts=request_opts))
    return tagged_requests

  def _create_tagged_request(
      self,
      model: str = None,
      request_opts: TestRequestOpts = None,
  ) -> Dict[str, Dict]:
    """Create a tagged test_platform.Request for the given model.

    Args:
      model: A model to run paygen AU tests on.
      request_opts: Overrides for the test_platform.Request.

    Returns:
      A dictionary mapping a string to a test_platform.Request.
    """
    if model:
      request_tag = self._REQUEST_WITH_MODEL_TAG_TEMPLATE % {
          'chromeos_build_name': self._chromeos_build_name,
          'tgt_channel': self._tgt_channel,
          'model': model,
          'update_type': self._update_type
      }
    else:
      request_tag = self._REQUEST_TAG_TEMPLATE % {
          'chromeos_build_name': self._chromeos_build_name,
          'tgt_channel': self._tgt_channel,
          'update_type': self._update_type
      }
    return {
        request_tag:
            MessageToDict(
                Request(
                    params=self._get_request_params(model, request_opts),
                    test_plan=self._get_test_plan()))
    }

  def _get_request_params(
      self,
      model: str = None,
      request_opts: TestRequestOpts = None,
  ) -> Request.Params:
    """Return test_platform.Params for the given model.

    Args:
      model: A model to run paygen AU tests on.
      request_opts: Overrides for the test_platform.Request.

    Returns:
      A .Params specific to the model.
    """
    params = Request.Params()
    # Params which can be overriden.
    params.time.maximum_duration.seconds = (
        request_opts.timeout.seconds or self._AUTOTEST_DEFAULT_TIMEOUT.seconds)
    params.retry.max = (
        request_opts.max_retries or self._AUTOTEST_DEFAULT_MAX_RETRIES)
    params.retry.allow = bool(params.retry.max > 0)

    if self._critical:
      params.test_execution_behavior = Request.Params.TestExecutionBehavior.CRITICAL

    # Non-CTS traffic uses MANAGED_POOL_QUOTA (go/managed-pools-deprecation).
    params.scheduling.managed_pool = \
        Request.Params.Scheduling.MANAGED_POOL_QUOTA
    params.scheduling.qs_account = self._quota_scheduler_account

    if model:
      params.hardware_attributes.model = model
    sw_dep = params.software_dependencies.add()
    sw_dep.chromeos_build = self._chromeos_build_name

    # This is used to create the swarming DUT dimensions, thus it's the
    # "test build target", which is what is deployed in the lab.
    params.software_attributes.build_target.name = self._test_build_target

    params.metadata.test_metadata_url = self._tgt_archive_uri
    params.metadata.debug_symbols_archive_url = self._tgt_archive_uri
    params.metadata.container_metadata_url = self._tgt_container_metadata_uri

    params.decorations.autotest_keyvals['build'] = self._chromeos_build_name
    params.decorations.autotest_keyvals['suite'] = self._suite_name
    tags = self.get_test_runner_tags(model)
    request_tags = [
        '{}:{}'.format(key, value) for key, value in sorted(tags.items())
    ]
    params.decorations.tags.extend(request_tags)

    return params

  def get_test_runner_tags(self, model: str = None) -> Dict[str, str]:
    """Generates test_runner build tags for the given model.

    Args:
      model: A model to run paygen AU tests on.

    Returns:
      A dictionary of test_runner build tags specific to the model.
    """
    tags = {
        'label-pool': self._quota_scheduler_label_pool,
        'build': self._chromeos_build_name,
        'label-board': self._test_build_target,
        'suite': self._suite_name,
        'quota_account': self._quota_scheduler_account,
    }
    if model:
      tags['label-model'] = model
    return tags


class PaygenTestingApi(recipe_api.RecipeApi):
  """A module for CrOS-specific paygen testing steps."""

  PaygenTestConfig = PaygenTestConfig

  def __init__(self, properties: PaygenTestingProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._test_request_opts = properties.test_request_opts
    self._quota_scheduler_account = QS_ACCOUNT
    self._quota_scheduler_label_pool = LABEL_POOL
    if properties.quota_scheduler_config:
      self._quota_scheduler_account = \
          properties.quota_scheduler_config.account or \
          self._quota_scheduler_account
      self._quota_scheduler_label_pool = \
          properties.quota_scheduler_config.label_pool or \
          self._quota_scheduler_label_pool
    self._retry_allowlist_qs_account = properties.retry_allowlist_qs_account
    self._retry_allowlist_build_target = properties.retry_allowlist_build_target

  @property
  def qs_account(self):
    """Returns the configured QS account."""
    return self._quota_scheduler_account

  def override_qs_account(self, qs_account):
    """Overrides whatever QS account was set via properties"""
    self._quota_scheduler_account = qs_account

  def _get_channel_from_paygen_request(
      self, gen_req: GenerationRequest) -> Optional['common_pb2.Channel']:
    """Get the target channel from a paygen request input properties.

    When creating a build report we look at the input arguments of the finished
    paygen builders. In the generation_request we pull the target channel and
    return this for reporting. Deals with the one_of by returning the first
    found.

    Args:
      gen_req: A GenerationRequest struct, as extracted from a broader build_pb2.Build request.
    Returns:
      A chromiumos.Channel.
    """
    if gen_req.HasField('tgt_signed_image'):
      return self.m.cros_release_util.channel_long_string_to_enum(
          gen_req.tgt_signed_image.build.channel)
    if gen_req.HasField('tgt_unsigned_image'):
      return self.m.cros_release_util.channel_long_string_to_enum(
          gen_req.tgt_unsigned_image.build.channel)
    if gen_req.HasField('tgt_dlc_image'):
      return self.m.cros_release_util.channel_long_string_to_enum(
          gen_req.tgt_dlc_image.build.channel)
    return None  #pragma: nocover

  def create_paygen_build_report_payload(
      self, req: PaygenProperties.PaygenRequest, payload_uri: str,
      recovery_key_version: Optional[int] = None) -> BuildReport.Payload:
    """Prepare payload information for the release pubsub.

    Args:
      req: The paygen request that was used.
      payload_uri: The uri of the generated payload.
      recovery_key_version: version of the recovery key if provided. Default
        None.

    Returns:
      A Payload containing payload information for the pubsub.
    """

    # If paygen was skipped (minios) this will be empty, so skip it.
    if not payload_uri:
      return None

    # Assign generation request for shorthand access.
    gen_req = req.generation_request

    # Determine payload type from the paygen request.
    payload_type = BuildReport.Payload.PayloadType.PAYLOAD_TYPE_STANDARD
    if gen_req and gen_req.minios:
      payload_type = BuildReport.Payload.PayloadType.PAYLOAD_TYPE_MINIOS
    elif gen_req.HasField('tgt_dlc_image'):
      payload_type = BuildReport.Payload.PayloadType.PAYLOAD_TYPE_DLC

    payload_json_path = '{}.json'.format(payload_uri)
    payload_info = self.m.gsutil.cat(
        payload_json_path, name='cat {}'.format(payload_json_path),
        stdout=self.m.raw_io.output(add_output_log=True)).stdout
    payload_info = json.loads(payload_info)

    is_delta = BuildReport.BuildArtifact.Type.PAYLOAD_FULL
    if payload_info.get('is_delta', False):
      is_delta = BuildReport.BuildArtifact.Type.PAYLOAD_DELTA

    return BuildReport.Payload(
        payload=BuildReport.BuildArtifact(
            type=is_delta,
            uri=URI(gcs=payload_uri),
            sha256=payload_info['sha256_hex'],
        ), payload_type=payload_type, appid=payload_info['appid'],
        channel=self._get_channel_from_paygen_request(gen_req),
        metadata_signature=payload_info['metadata_signature'],
        metadata_size=int(payload_info['metadata_size']),
        source_version=payload_info.get('source_version', None),
        target_version=payload_info['target_version'], size=int(
            payload_info['size']), recovery_key_version=recovery_key_version)

  @exponential_retry(retries=5, delay=timedelta(minutes=2))
  def _discover_source_test_full_payload(self, root_uri: str) -> FullPayload:
    """Find a source full unsigned image to act as starting image for tests.

    This is wrapped in an exponential retry because it's possible that the full
    payload has not finished generating and we might need to wait for it to
    begin testing using it.

    Args:
      root_uri: The URI to search GS recursively for the full unsigned payload.

    Returns:
      A cros_source.FullPayload instance.

    Raises:
      StepFailure: If the image can't be found.
    """
    src_payloads = self.m.cros_storage.discover_gs_artifacts(
        root_uri, parse_types=[self.m.cros_storage.FullPayload.parse_uri])
    src_payload = None
    for payload in src_payloads:
      if not payload.key:
        src_payload = payload
        break
    if not src_payload:
      raise StepFailure(
          'no source full test payload found: {}'.format(root_uri))
    return src_payload

  def create_paygen_test_config(self, tgt_payload: Payload,
                                delta_type: common_pb2.DeltaType,
                                src_version: str = None,
                                src_channel: str = None,
                                applicable_models: List[str] = None,
                                src_bucket: str = None) -> 'PaygenTestConfig':
    """Create a PaygenTestConfig for a test FullPayload or DeltaPayload.

    Args:
      tgt_payload: The payload to be tested.
      delta_type: The type of update we are doing with this payload.
      src_version: The version of the image to test updating from
        (e.g. '13373.0.0'). Required if the payload is a FullPayload, required
        to be None if it's a DeltaPayload.
      src_channel: The channel of the image to test updating from
        (e.g. 'canary-channel'). Required if the payload is a FullPayload,
        required to be None if it's a DeltaPayload.
      applicable_models: A list of models that a paygen test should
        run against.
      src_bucket: A bucket to use as src_image bucket instead of pulling
        bucket from the tgt. This is useful in environments where the bucket
        being written to doesn't contain older images (i.e. in staging).

    Returns:
      A PaygenTestConfig or None if no source payload exists or unsupported
      Payload provided.
    """
    tgt_image = tgt_payload._tgt_image
    build_target_name = tgt_image._artifact_root.build_target_name
    tgt_channel = tgt_image._artifact_root.channel
    tgt_version = tgt_image._artifact_root.version

    if isinstance(tgt_payload, self.m.cros_storage.DeltaPayload):
      is_delta_update = True
      src_image = tgt_payload._src_image
      src_version = src_image._artifact_root.version
    elif isinstance(tgt_payload, self.m.cros_storage.FullPayload):
      if not (src_version and src_channel):
        raise StepFailure(
            'src version and channel must be specified for FullPayload AU tests'
        )
      is_delta_update = False
      src_artifact_root = self.m.cros_storage.ArtifactRoot(
          bucket=src_bucket or tgt_image._artifact_root.bucket,
          build_target_name=build_target_name, channel=src_channel,
          version=src_version)
      src_image = self.m.cros_storage.UnsignedImage(
          artifact_root=src_artifact_root, milestone=tgt_image._milestone,
          image_type=common_pb2.IMAGE_TYPE_TEST)
    else:
      # Invalid Payload type given.
      raise StepFailure(
          'AU tests only supported for FullPayloads or DeltaPayloads')

    # Get source full test payload, if this is an N2N test, then we might not
    # have generated it, thus wrap the discovery loop in an exponential retry.
    src_payload = self._discover_source_test_full_payload(
        src_image._artifact_root.uri)

    tgt_archive_uri = tgt_image.archive_uri
    src_artifact_uri = src_image._artifact_root.uri

    container_metadata_info = self.m.metadata.METADATA_PAYLOADS['container']
    tgt_container_metadata_uri = self.m.path.join(
        src_artifact_uri, self.m.metadata.gspath(container_metadata_info))

    # Fetch target test requirements to get the proper build target.
    # We can't take the build target directly from the artifact because it won't
    # necessarily match what CTP expects (e.g. atlas-kernelnext vs atlas).
    # TODO(b/209487309): Simplify finding the proper build target, ideally we
    # wouldn't need to look at test config to figure this out.
    test_build_target = build_target_name

    # Construct Rubik child builder name.
    target_test_reqs = self.m.cros_test_plan.get_target_test_requirements(
        builders=[
            self.m.cros_release_util.release_builder_name(build_target_name)
        ])
    for target_requirements in target_test_reqs['perTargetTestRequirements']:
      if target_requirements.get('targetCriteria',
                                 {}).get('buildTarget',
                                         '') == build_target_name:
        hw_test_cfg = target_requirements.get('hwTestCfg', {}).get('hwTest', [])
        if hw_test_cfg:
          if 'skylabBoard' in hw_test_cfg[0]:
            test_build_target = hw_test_cfg[0]['skylabBoard']

    critical = False
    # Tests should be critical for high/med prio builds.
    # See go/cros-infra:release-tests-automatic-retries for context.
    # TODO(b/293879623): Remove per-build-target allow list once rollout is complete.
    if self._quota_scheduler_account in self._retry_allowlist_qs_account and build_target_name in self._retry_allowlist_build_target:
      critical = True

    return PaygenTestConfig(
        test_build_target=test_build_target,
        build_target_name=build_target_name, tgt_channel=tgt_channel,
        tgt_payload_uri=tgt_payload.uri, tgt_archive_uri=tgt_archive_uri,
        tgt_container_metadata_uri=tgt_container_metadata_uri,
        tgt_version=tgt_version, src_payload_uri=src_payload.uri,
        src_artifact_uri=src_artifact_uri, src_version=src_version,
        is_delta_update=is_delta_update, delta_type=delta_type,
        applicable_models=applicable_models,
        quota_scheduler_account=self._quota_scheduler_account,
        quota_scheduler_label_pool=self._quota_scheduler_label_pool,
        critical=critical)

  def set_up_paygen_test_configs(
      self, request: PaygenProperties.PaygenRequest,
      artifacts: List[GenerationResponse.VersionedArtifact]
  ) -> Optional[List[PaygenTestConfig]]:
    """Set up test configs for a paygen response, if applicable.

    Given a PaygenRequest and a GenerationResponse, determine if this payload
    should have testing applied and if so set up and return the test configs
    to be scheduled.

    Args:
      request: request object to introspect.
      artifacts: artifacts from payload generation.

    Returns:
      List of paygen test configs to schedule.
    """
    with self.m.step.nest('setting up paygen test config') as presentation:
      if request.generation_request.dryrun:
        presentation.step_text = 'dry run, skip testing'
        return None
      if not request.autoupdate_test_configs:
        presentation.step_text = 'no test configured, skip testing'
        return None
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
      for artifact in artifacts:
        tgt_payload = (
            # Notice FullPayload doesn't get a bucket. That's because a full payload
            # source is created in paygen_testing.create_paygen_test_config().
            self.m.cros_storage.FullPayload.parse_uri(artifact.remote_uri,
                                                      milestone) or
            self.m.cros_storage.DeltaPayload.parse_uri(artifact.remote_uri,
                                                       milestone, src_bucket))
        for test_config in request.autoupdate_test_configs:
          paygen_test_configs.append(
              self.create_paygen_test_config(
                  tgt_payload, src_version=test_config.src_version,
                  src_channel=test_config.src_channel,
                  delta_type=test_config.delta_type,
                  applicable_models=test_config.applicable_models,
                  src_bucket=src_bucket))

      return paygen_test_configs

  def create_au_test_tagged_requests(self,
                                     paygen_test_configs: List[PaygenTestConfig]
                                    ) -> Tuple[Dict[str, str], Dict[str, Dict]]:
    """Takes in paygen test configs and creates au test requests.

    This is its own method mainly for testing.
    """
    tagged_requests = {}
    # Schedule with parent id tag.
    parent_buildbucket_id = str(self.m.buildbucket.build.id)
    bb_tags = {'parent_buildbucket_id': parent_buildbucket_id}
    # Fill out requests and update the bb_tags which will be applied to the
    # ctp runs overall. They should be identical, but the last update of bb_tags
    # wins.
    for ptc in paygen_test_configs:

      ctp_tagged_request = ptc.to_ctp_tagged_requests(self._test_request_opts)

      # Since the tag on the tagged request is not guaranteed to be unique,
      # iterate through all the tags and requests and if a tag is present
      # already merge the requests. In this case, merge means concat their
      # autotestInvocations arrays, as that's where the variation lives. (Legacy
      # doesn't even bother breaking them out by tags, it puts everything under
      # the tag "default".
      for key, value in ctp_tagged_request.items():
        if key in tagged_requests:
          existing = tagged_requests[key]
          existing['testPlan']['enumeration']['autotestInvocations'].extend(
              value['testPlan']['enumeration']['autotestInvocations'])
        else:
          tagged_requests.update({key: value})
      bb_tags.update(ptc.get_test_runner_tags())
    return bb_tags, tagged_requests

  def schedule_au_tests(self, paygen_test_configs: List[PaygenTestConfig]
                       ) -> Optional[List[Build]]:
    """Schedule Paygen autoupdate (AU) tests.

    Create a cros_test_platform build request to launch AU tests. This
    schedules the ctp request per model. The reason to do this is because
    the full requests can be greater than the buildbucket input property
    size which is currently 1MB, see crbug.com/1336469.

    Args:
      paygen_test_configs: A list of PaygenTestConfigs for which to schedule au_tests.

    Returns:
      The scheduled buildbucket builds.
    """
    # bb_tags here doesn't include label-model so it applies universally
    # even though we're scheduling per model below we can apply it to each
    # individual request.
    bb_tags, tagged_requests = self.create_au_test_tagged_requests(
        paygen_test_configs)

    if not tagged_requests:
      return None

    # This is definitely an inefficient loop to break the requests up,
    # but N should remain small. See doc string for why we do this.
    def _get_label_model_from_ptc(ptc: Dict[str, Dict]) -> str:
      tags = ptc.get('params', {}).get('decorations', {}).get('tags', [])
      # Pull the matching label-model field or 'no-model-found'.
      return next(
          iter([x for x in tags if x.startswith('label-model:')]),
          'label-model:no-model-found')

    models = [_get_label_model_from_ptc(v) for k, v in tagged_requests.items()]

    skylab_requests = []
    for m in sorted(set(models)):
      model_tagged_request = collections.OrderedDict()
      for k, v in tagged_requests.items():
        if _get_label_model_from_ptc(v) == m:
          model_tagged_request[k] = v
      bb_tags['label-model'] = m[len('label-model:'):].strip()
      skylab_requests.append(
          self.m.skylab.schedule_ctp_requests(model_tagged_request,
                                              bb_tags=bb_tags))
      del bb_tags['label-model']

    return skylab_requests
