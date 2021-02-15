# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with Paygen and its config."""

from google.protobuf import duration_pb2
from google.protobuf.json_format import MessageToDict
from collections import namedtuple
from copy import deepcopy
import json
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure
from os import path

from PB.chromite.api import test_metadata
from PB.chromite.api.payload import DLCImage as DLCImage_pb2
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2
import PB.chromiumos.common as common_pb2
from PB.recipes.chromeos.paygen import AutoupdateTestConfig
from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties
from PB.test_platform.request import Request

DEFAULT_DELTA_TYPES = [
    common_pb2.STEPPING_STONE, common_pb2.OMAHA, common_pb2.NO_DELTA,
    common_pb2.MILESTONE, common_pb2.FSI
]

PAYGEN_JSON_GS_PATH = 'gs://chromeos-build-release-console/paygen.json'

QS_ACCOUNT = 'legacypool-bvt'
LABEL_POOL = 'quota'

CategorizedGenerationRequests = namedtuple('CategorizedGenerationRequests', [
    'full_test_payload_requests', 'delta_test_payload_requests',
    'non_test_payload_requests'
])


class PaygenTestConfig(object):
  """A single test configuration.

  Stores and generates arguments for running autoupdate_EndToEndTest.

  Paygen Autotest documentation:
  go/cros-au-testplan#heading=h.9pokikke2eh

  autoupdate_EndToEndTest control file:
  http://cs/chromeos_public/src/third_party/autotest/files/server/site_tests/autoupdate_EndToEndTest/control

  autoupdate_EndToEndTest file:
  https://source.corp.google.com/chromeos_public/src/third_party/autotest/files/server/site_tests/autoupdate_EndToEndTest/autoupdate_EndToEndTest.py

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
  _REQUEST_TAG_TEMPLATE = '%(chromeos_build_name)s-%(tgt_channel)s'
  _REQUEST_WITH_MODEL_TAG_TEMPLATE = (
      '%(chromeos_build_name)s-%(tgt_channel)s-%(model)s')

  def __init__(self, build_target_name, tgt_channel, tgt_version,
               tgt_payload_uri, tgt_archive_uri, is_delta_update, delta_type,
               src_version, src_payload_uri, src_artifact_uri,
               applicable_models=None):
    """Initialize a test configuration.

    Args:
      build_target_name (str): The name of the build target being tested
        (e.g. auron_paine).
      tgt_channel (str): The channel of the target payload
        (e.g. 'canary-channel').
      tgt_version (str): The target image version (e.g. '13373.0.0').
      tgt_payload_uri (str): The target payload URI.
      tgt_archive_uri (str): The location of target build archive artifacts.
      is_delta_update (bool): Whether this is a delta update test.
      delta_type (DeltaType): The type of update to do with the payload.
      src_version (str): The source image version (e.g. '13373.0.0').
      src_payload_uri (str): The source payload URI.
      src_artifact_uri (str): The location of source build artifacts.
      applicable_models (list[str]): A list of models that this config should
        run against. None indicates it can run on any build_target.
    """
    self._build_target_name = build_target_name
    self._tgt_channel = tgt_channel
    self._tgt_version = tgt_version
    self._tgt_payload_uri = tgt_payload_uri
    self._tgt_archive_uri = tgt_archive_uri

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

  def _get_test_plan(self):
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

  def _get_test_args(self):
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

  def to_ctp_tagged_requests(self, models=None, request_opts=None):
    """Turn self into a dict of tagged test_platform.Requests.

    Creates one request per testable model or one request with no model
    specified if self._applicable_models and models is None.

    Args:
      models (list(str)): A list of models to run paygen AU tests on.
      request_opts (TestRequestOpts): Overrides for the test_platform.Request.

    Returns:
       A dictionary of string to test_platform.Request objects.
    """
    if models is None and self._applicable_models is None:
      return self._create_tagged_request(request_opts=request_opts)

    tagged_requests = {}
    testable_models = self._get_testable_models(models)
    for model in testable_models:
      tagged_requests.update(
          self._create_tagged_request(model=model, request_opts=request_opts))
    return tagged_requests

  def _get_testable_models(self, models=None):
    """Returns a list of models for which to run AU tests on.

    Testable models are:
      * All members of models if self._applicable_models is None.
      * All members of self._applicable_models if models is None.
      * The intersection of models and self._applicable_models if both are
          non-empty.

    Args:
      models (list(str)): A list of models to run paygen AU tests on.

    Returns:
      A set of testable models as defined in the description.
    """
    if not models:
      return self._applicable_models
    if not self._applicable_models:
      return models
    return set(models) & set(self._applicable_models)

  def _create_tagged_request(self, model=None, request_opts=None):
    """Create a tagged test_platform.Request for the given model.

    Args:
      model (str): A model to run paygen AU tests on.
      request_opts (TestRequestOpts): Overrides for the test_platform.Request.

    Returns:
      A dictionary mapping a string to a test_platform.Request.
    """
    if model:
      request_tag = self._REQUEST_WITH_MODEL_TAG_TEMPLATE % {
          'chromeos_build_name': self._chromeos_build_name,
          'tgt_channel': self._tgt_channel,
          'model': model
      }
    else:
      request_tag = self._REQUEST_TAG_TEMPLATE % {
          'chromeos_build_name': self._chromeos_build_name,
          'tgt_channel': self._tgt_channel
      }
    return {
        request_tag:
            MessageToDict(
                Request(
                    params=self._get_request_params(model, request_opts),
                    test_plan=self._get_test_plan()))
    }

  def _get_request_params(self, model=None, request_opts=None):
    """Return test_platform.Params for the given model.

    Args:
      model (str): A model to run paygen AU tests on.
      request_opts (TestRequestOpts): Overrides for the test_platform.Request.

    Returns:
      A test_platform.Request.Params specific to the model.
    """
    params = Request.Params()
    # Params which can be overriden.
    params.time.maximum_duration.seconds = (
        request_opts.timeout.seconds or self._AUTOTEST_DEFAULT_TIMEOUT.seconds)
    params.retry.max = (
        request_opts.max_retries or self._AUTOTEST_DEFAULT_MAX_RETRIES)
    params.retry.allow = bool(params.retry.max > 0)

    # Non-CTS traffic uses MANAGED_POOL_QUOTA (go/managed-pools-deprecation).
    params.scheduling.managed_pool = Request.Params.Scheduling.MANAGED_POOL_QUOTA
    params.scheduling.qs_account = QS_ACCOUNT

    if model:
      params.hardware_attributes.model = model
    sw_dep = params.software_dependencies.add()
    sw_dep.chromeos_build = self._chromeos_build_name
    # TODO(crbug.com/1122854): Some non-unibuild boards run on a DUT with a
    # different board label (e.g. eve-arc-r maps to eve).
    params.software_attributes.build_target.name = self._build_target_name

    params.metadata.test_metadata_url = self._tgt_archive_uri
    params.metadata.debug_symbols_archive_url = self._tgt_archive_uri

    params.decorations.autotest_keyvals['build'] = self._chromeos_build_name
    params.decorations.autotest_keyvals['suite'] = self._suite_name
    tags = self._get_test_runner_tags(model)
    request_tags = ['{}:{}'.format(key, value) for key, value in tags.items()]
    params.decorations.tags.extend(request_tags)

    return params

  def _get_test_runner_tags(self, model=None):
    """Generates test_runner build tags for the given model.

    Args:
      model (str): A model to run paygen AU tests on.

    Returns:
      A dictionary of test_runner build tags specific to the model.
    """
    tags = {
        'label-pool': LABEL_POOL,
        'build': self._chromeos_build_name,
        'label-board': self._build_target_name,
        'suite': self._suite_name,
        'quota_account': QS_ACCOUNT,
    }
    if model:
      tags['label-model'] = model
    return tags


class CrosPaygenApi(recipe_api.RecipeApi):
  """A module for CrOS-specific paygen steps."""

  PaygenTestConfig = PaygenTestConfig

  def __init__(self, properties, *args, **kwargs):
    super(CrosPaygenApi, self).__init__(*args, **kwargs)
    self._internal_config = None
    self._paygen_json_gs_path = PAYGEN_JSON_GS_PATH
    self._test_request_opts = properties.test_request_opts

  @property
  def paygen_children_timeout_sec(self):
    """Get the currently configured paygen timeout in seconds."""
    return 6 * 60 * 60

  @property
  def paygen_orchestrator_timeout_sec(self):
    """Get the currently configured paygen orchestrator timeout in seconds.

    This contains the duration expected for paygen children.

    Returns
      The int max number of seconds the paygen orchestrator should take.
    """
    return self.paygen_children_timeout_sec + 1 * 60 * 60

  @property
  def _config(self):
    """Lazily loaded copy of the entire configuration in paygen.json."""
    if not self._internal_config:
      raw_config = self._get_gs_config()
      try:
        self._internal_config = json.loads(raw_config)
      except ValueError:
        raise StepFailure('config json could not be deserialized')
      # Do some basic checks on the configuration.
      if ('delta' not in self._internal_config or
          len(self._internal_config['delta']) == 0):
        raise StepFailure('config json was not formatted correctly')
    # Returns immutable copy.
    return deepcopy(self._internal_config)

  def _get_gs_config(self):
    """Pull and load the current paygen configuration as a string."""
    with self.m.step.nest('get paygen json') as pres:
      cat_res = self.m.gsutil.cat(self._paygen_json_gs_path, infra_step=True,
                                  stdout=self.m.raw_io.output())
      ret = cat_res.stdout.strip()
      pres.logs['paygen.json'] = ret
      return ret

  def _flatten_config(self, board_config):
    """Flatten a board_config so we can query it more easily."""
    new_b = deepcopy(board_config)
    new_b.update(board_config['board'])
    del new_b['board']
    return new_b

  @property
  def default_delta_types(self):
    return DEFAULT_DELTA_TYPES

  def get_builder_config(self, builder_name, **kwargs):
    """Return the configs matching the query or [].

    Note that all comparisons are made _in lower case_!

    Args:
      builder_name (str): The name of the builders to return configuration for.
      **kwargs: Match keyword to top level dictionary contents. For example
                passing delta_payload_tests=true will match only if matched.

    Returns:
      A list of dictionaries of the matching configurations. For example:

      [
       {
        "board": {
                "public_codename": "cyan",
                "is_active": true,
                "builder_name": "cyan"
        },
        "delta_type": "MILESTONE",
        "channel": "stable",
        "chrome_os_version": "13020.87.0",
        "chrome_version": "83.0.4103.119",
        "generate_delta": true,
        "delta_payload_tests": true,
        "full_payload_tests": false
        },
       {...},
       {...}
      ]
    """
    match_boards = []
    for b in self._config['delta']:
      b = self._flatten_config(b)
      if b['builder_name'].lower() == builder_name.lower():
        if all(
            [k in b and b[k].lower() == v.lower() for k, v in kwargs.items()]):
          match_boards.append(b)
    return match_boards

  def get_n2n_requests(self, tgt_artifacts, bucket, verify, dryrun):
    """Generate a N2N testing payloads.

    We will examine all the artifacts in tgt artifacts for unsigned
    test images and generate n2n requests (a request that updates to
    and from the same version.

    Args:
      tgt_artifacts (list[cros_storage.Image]): Available tgt images.
      bucket (str): The bucket containing the requests (and destination).
      verify (bool): Should we run payload verification.
      dryrun (bool): Should we not upload resulting artifacts.

    Returns:
      A list[GenerationRequest] or [].
    """
    reqs = []
    for tgt in tgt_artifacts:
      if (tgt.image_type == common_pb2.ImageType.Value('TEST') and
          isinstance(tgt, UnsignedImage_pb2)):
        reqs.append(
            GenerationRequest(src_unsigned_image=tgt, tgt_unsigned_image=tgt,
                              bucket=bucket, verify=verify, keyset='',
                              dryrun=dryrun))
    return reqs

  def get_delta_requests(self, payload_def, src_artifacts, tgt_artifacts,
                         bucket, verify, keyset, dryrun):
    """Examine def, source, and target and return list(GenerationRequests).

    If there isn't a matching source and target available, then return [].

    bucket, verify, keyset, and dryrun are all used to fill out the
    GenerationRequest().

    Args:
      payload_def (dict): A singular configuration from pulled config.
      src_artifacts (list[cros_storage.Image]): Available src images.
      tgt_artifacts (list[cros_storage.Image]): Available tgt images.
      bucket (str): The bucket containing the requests (and destination).
      verify (bool): Should we run payload verification.
      keyset (str): The keyset of the payload.
      dryrun (bool): Should we not upload resulting artifacts.

    Returns:
      A completed list[GenerationRequest] or [].
    """
    reqs = []

    # See if we're configured to do deltas at all.
    if not payload_def['generate_delta']:
      return reqs  # pragma: nocover

    # For each src query all the target artifacts for a match (naively).
    for tgt in tgt_artifacts:
      tgt_type = type(tgt)
      for src in src_artifacts:
        # Create and compare the versions, we don't paygen backwards.
        v_src = self.m.cros_version.Version.from_string(src.build.version)
        v_tgt = self.m.cros_version.Version.from_string(tgt.build.version)

        if v_tgt <= v_src:
          # TODO(crbug.com/1122854): Add test, remove pragma.
          continue  # pragma: nocover

        # Validate the artifact pair.
        if (tgt_type != type(src) or tgt.image_type != src.image_type or
            tgt.build.channel != src.build.channel or
            src.build.version != payload_def['chrome_os_version']):
          continue  # pragma: nocover

        elif isinstance(src, SignedImage_pb2):
          reqs.append(
              GenerationRequest(src_signed_image=src, tgt_signed_image=tgt,
                                bucket=bucket, verify=verify, keyset=keyset,
                                dryrun=dryrun))
        elif isinstance(src, UnsignedImage_pb2):
          # We don't create delta paygens for unsigned recovery images.
          if src.image_type == common_pb2.ImageType.Value('RECOVERY'):
            continue  # pragma: nocover
          reqs.append(
              GenerationRequest(src_unsigned_image=src, tgt_unsigned_image=tgt,
                                bucket=bucket, verify=verify, keyset=keyset,
                                dryrun=dryrun))
        elif isinstance(src, DLCImage_pb2):
          if not self.m.cros_storage.DLCImage.compatible(tgt, src):
            continue  # pragma: nocover
          reqs.append(
              GenerationRequest(src_dlc_image=src, tgt_dlc_image=tgt,
                                bucket=bucket, verify=verify, keyset='',
                                dryrun=dryrun))
    return reqs

  def get_full_requests(self, tgt_artifacts, bucket, verify, keyset, dryrun):
    """Get the configured full requests for a set of artifacts.

    Args:
      tgt_artifacts (list[cros_storage.Image]): Available tgt images.
      bucket (str): The bucket containing the requests (and destination).
      verify (bool): Should we run payload verification.
      keyset (str): The keyset of the payload.
      dryrun (bool): Should we not upload resulting artifacts.

    Returns:
      A completed list[GenerationRequest] or [].
    """
    reqs = []
    for tgt in tgt_artifacts:
      if isinstance(tgt, SignedImage_pb2):
        reqs.append(
            GenerationRequest(full_update=True, tgt_signed_image=tgt,
                              bucket=bucket, verify=verify, keyset=keyset,
                              dryrun=dryrun))
      elif isinstance(tgt, UnsignedImage_pb2):
        # We don't create full payloads for unsigned recovery images.
        if tgt.image_type == common_pb2.ImageType.Value('RECOVERY'):
          continue  #  pragma: nocover
        reqs.append(
            GenerationRequest(full_update=True, tgt_unsigned_image=tgt,
                              bucket=bucket, verify=verify, keyset=keyset,
                              dryrun=dryrun))
      elif isinstance(tgt, DLCImage_pb2):
        reqs.append(
            GenerationRequest(full_update=True, tgt_dlc_image=tgt,
                              bucket=bucket, verify=verify, keyset='',
                              dryrun=dryrun))

    # TODO(crbug.com/1122854): The chromite code checks the number of mp and
    # premp signing requests here. We are generally more relaxed at enforcing
    # this at the moment. We maybe revist this philosophy generally as we
    # approach launching this.
    return reqs

  def run_paygen_builders(
      self, gen_reqs, configured_payloads,
      delta_payload_test_override=PaygenOrchestratorProperties.RESPECT_CONFIG,
      full_payload_test_override=PaygenOrchestratorProperties.RESPECT_CONFIG):
    """Launch paygen builders to generate payloads and run configured tests.

    Args:
      gen_reqs (list[GenerationRequest]): The GenerationRequests for which to
        find tests and schedule.
      configured_payloads (list[dict]): Configs for the payloads we are
        generating and testing.
      delta_payload_test_override (PayloadTestsOverride): Whether to override
        the configured delta payload testing policy.
      full_payload_test_override (PayloadTestsOverride): Whether to override the
        configured full payload testing policy.

    Returns:
      A list of completed builds.
    """
    sorted_gen_reqs = self._categorize_generation_requests(gen_reqs)

    # Create non-test payload buildbucket requests.
    cbr = [
        self._create_bb_schedule_request(x)
        for x in sorted_gen_reqs.non_test_payload_requests
    ]
    # Create full test payload buildbucket requests.
    cbr.extend(
        self._schedule_full_test_payloads(
            sorted_gen_reqs.full_test_payload_requests, configured_payloads,
            full_payload_test_override))
    # Create delta test payload buildbucket requests.
    cbr.extend(
        self._schedule_delta_test_payloads(
            sorted_gen_reqs.delta_test_payload_requests, configured_payloads,
            delta_payload_test_override))
    # Run the buildbucket requests and return the build results.
    return self.m.buildbucket.run(cbr, timeout=self.paygen_children_timeout_sec,
                                  step_name='running children')

  def _schedule_delta_test_payloads(
      self, gen_reqs, configured_payloads,
      test_override=PaygenOrchestratorProperties.RESPECT_CONFIG):
    """Create bb requests to generate delta test payloads and launch tests.

    Args:
      gen_reqs (list[GenerationRequest]): The delta test payload
        GenerationRequests for which to find tests and schedule.
      configured_payloads (list[dict]): Configs for the payloads we are
        generating and testing.
      test_override (PayloadTestsOverride): Whether to override the configured
        delta payload testing policy.

    Returns:
      A list[ScheduleBuildRequest] for the delta test payloads.
    """
    # If FORCE_NO_TESTS create schedule requests with only GenerationRequests.
    if (test_override == PaygenOrchestratorProperties.FORCE_NO_TESTS):
      return [self._create_bb_schedule_request(gen_req) for gen_req in gen_reqs]

    always_test_delta = (
        test_override == PaygenOrchestratorProperties.FORCE_TESTS)

    schedule_requests = []
    for gen_req in gen_reqs:
      test_reqs = []
      # Get N2N test.
      if gen_req.tgt_unsigned_image == gen_req.src_unsigned_image:
        test_reqs.append(AutoupdateTestConfig(delta_type=common_pb2.N2N))
      # Match configs to the given GenerationRequest.
      cfgs = [
          cfg for cfg in configured_payloads if
          (cfg['channel'] == gen_req.tgt_unsigned_image.build.channel and
           cfg['chrome_os_version'] == gen_req.src_unsigned_image.build.version)
      ]
      # Get tests from matched configured payloads.
      for cfg in cfgs:
        if cfg['delta_payload_tests'] or always_test_delta:
          test_reqs.append(
              AutoupdateTestConfig(
                  delta_type=common_pb2.DeltaType.Value(cfg['delta_type']),
                  applicable_models=cfg.get('applicable_models')))
      schedule_requests.append(
          self._create_bb_schedule_request(gen_req, test_reqs))
    return schedule_requests

  def _schedule_full_test_payloads(
      self, gen_reqs, configured_payloads,
      test_override=PaygenOrchestratorProperties.RESPECT_CONFIG):
    """Create bb requests to generate full test payloads and launch tests.

    Args:
      gen_reqs (list[GenerationRequest]): The full test payload
        GenerationRequests for which to find tests and schedule.
      configured_payloads (list[dict]): Configs for the payloads we are
        generating and testing.
      test_override (PayloadTestsOverride): Whether to override the configured
        full payload testing policy.

    Returns:
      A list[ScheduleBuildRequest] for the full test payloads.
    """
    # If FORCE_NO_TESTS create schedule requests with only GenerationRequests.
    if (test_override == PaygenOrchestratorProperties.FORCE_NO_TESTS):
      return [self._create_bb_schedule_request(gen_req) for gen_req in gen_reqs]

    always_test_full = (
        test_override == PaygenOrchestratorProperties.FORCE_TESTS)

    schedule_requests = []
    for gen_req in gen_reqs:
      test_reqs = []
      # Get N2N test.
      test_reqs = [
          AutoupdateTestConfig(
              src_version=gen_req.tgt_unsigned_image.build.version,
              src_channel=gen_req.tgt_unsigned_image.build.channel,
              delta_type=common_pb2.N2N)
      ]
      # Match configs to the given GenerationRequest.
      cfgs = [
          cfg for cfg in configured_payloads
          if cfg['channel'] == gen_req.tgt_unsigned_image.build.channel
      ]
      # Get tests from matched configured payloads.
      for cfg in cfgs:
        if cfg['full_payload_tests'] or always_test_full:
          test_reqs.append(
              AutoupdateTestConfig(
                  src_version=cfg['chrome_os_version'],
                  src_channel=cfg['channel'] + '-channel',
                  delta_type=common_pb2.DeltaType.Value(cfg['delta_type']),
                  applicable_models=cfg.get('applicable_models')))
      schedule_requests.append(
          self._create_bb_schedule_request(gen_req, test_reqs))
    return schedule_requests

  def _categorize_generation_requests(self, gen_reqs):
    """Categorize the test payloads generation requests.

    Categorizes into three buckets: full test payloads, delta test payloads, and
    non-test payloads (all others).

    Args:
      gen_reqs (list[GenerationRequest]): The GenerationRequests to sort.

    Returns:
      Namedtuple CategorizedGenerationRequests.
     """
    full_test_reqs = []
    delta_test_reqs = []
    non_test_reqs = []

    for req in gen_reqs:
      if (req.WhichOneof('src_image_oneof') == 'src_unsigned_image' and
          req.src_unsigned_image.image_type == common_pb2.ImageType.Value(
              'TEST')):
        delta_test_reqs.append(req)
      elif (req.WhichOneof('tgt_image_oneof') == 'tgt_unsigned_image' and
            req.tgt_unsigned_image.image_type == common_pb2.ImageType.Value(
                'TEST')):
        full_test_reqs.append(req)
      else:
        non_test_reqs.append(req)
    return CategorizedGenerationRequests(full_test_reqs, delta_test_reqs,
                                         non_test_reqs)

  def _create_bb_schedule_request(self, generation_request, test_requests=None):
    """Create a ScheduleBuildRequest for a Paygen builder.

    Args:
      generation_request (GenerationRequest): Request to generate the desired
        payload.
      test_requests ([AutoupdateTestConfigs]): A list of tests to perform with
        the generated payload.

    Returns:
      A ScheduleBuildRequest for a Paygen builder.
    """
    test_requests = test_requests or []
    bucket = 'staging' if self.m.cros_infra_config.is_staging else 'release'
    return self.m.buildbucket.schedule_request(
        bucket=bucket, builder='paygen', properties={
            'request':
                MessageToDict(generation_request),
            'autoupdate_test_configs': [
                MessageToDict(x) for x in test_requests or {}
            ]
        })

  def create_paygen_test_config(self, tgt_payload, delta_type, src_version=None,
                                src_channel=None, applicable_models=None):
    """Create a PaygenTestConfig for a test FullPayload or DeltaPayload.

    Args:
      tgt_payload (Payload): The payload to be tested.
      delta_type (DeltaType): The type of update we are doing with this payload.
      src_version (str): The version of the image to test updating from
        (e.g. '13373.0.0'). Required if the payload is a FullPayload, required
        to be None if it's a DeltaPayload.
      src_channel (str): The channel of the image to test updating from
        (e.g. 'canary-channel'). Required if the payload is a FullPayload,
        required to be None if it's a DeltaPayload.
      applicable_models (list(str)): A list of models that a paygen test should
        run against.

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
            'source version and channel must be specified for FullPayload AU tests'
        )
      is_delta_update = False
      src_artifact_root = self.m.cros_storage.ArtifactRoot(
          bucket=tgt_image._artifact_root.bucket,
          build_target_name=build_target_name, channel=src_channel,
          version=src_version)
      src_image = self.m.cros_storage.UnsignedImage(
          artifact_root=src_artifact_root, milestone=tgt_image._milestone,
          image_type=common_pb2.ImageType.Value('TEST'))
    else:
      # Invalid Payload type given.
      raise StepFailure(
          'AU tests only supported for FullPayloads or DeltaPayloads')

    # Get source full test payload
    src_payloads = self.m.cros_storage.discover_gs_artifacts(
        src_image._artifact_root.uri,
        parse_types=[self.m.cros_storage.FullPayload.parse_uri])
    src_payload = None
    for payload in src_payloads:
      if not payload.key:
        src_payload = payload
        break
    if not src_payload:
      raise StepFailure('no source payload found')
    tgt_archive_uri = tgt_image.archive_uri
    src_artifact_uri = src_image._artifact_root.uri

    return PaygenTestConfig(
        build_target_name=build_target_name, tgt_channel=tgt_channel,
        tgt_payload_uri=tgt_payload.uri, tgt_archive_uri=tgt_archive_uri,
        tgt_version=tgt_version, src_payload_uri=src_payload.uri,
        src_artifact_uri=src_artifact_uri, src_version=src_version,
        is_delta_update=is_delta_update, delta_type=delta_type,
        applicable_models=applicable_models)

  def schedule_au_tests(self, paygen_test_configs, models=None):
    """Schedule Paygen autoupdate (AU) tests.

    Create a cros_test_platform build request to launch AU tests.

    Args:
      paygen_test_configs (list[PaygenTestConfig]): A list of PaygenTestConfigs
        for which to schedule au_tests.

    Returns:
      The scheduled buildbucket build.
    """
    tagged_requests = {}
    for ptc in paygen_test_configs:
      tagged_requests = ptc.to_ctp_tagged_requests(models,
                                                   self._test_request_opts)
    if not tagged_requests:
      return
    return self.m.skylab.schedule_ctp_requests(tagged_requests)
