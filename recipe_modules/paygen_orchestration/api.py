# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

"""API for orchestrating payload generation. Used by paygen_orchestrator."""
import collections

from google.protobuf.json_format import MessageToDict
from copy import deepcopy
import json
import math
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.chromite.api.payload import DLCImage as DLCImage_pb2
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2
import PB.chromiumos.common as common_pb2
from PB.recipes.chromeos.paygen import AutoupdateTestConfig
from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties

DEFAULT_DELTA_TYPES = [
    common_pb2.STEPPING_STONE, common_pb2.OMAHA, common_pb2.NO_DELTA,
    common_pb2.MILESTONE, common_pb2.FSI
]

PAYGEN_JSON_GS_PATH = 'gs://chromeos-build-release-console/paygen.json'


class PaygenOrchestrationApi(recipe_api.RecipeApi):
  """A module for CrOS-specific paygen orchestration steps."""

  def __init__(self, properties, *args, **kwargs):
    super(PaygenOrchestrationApi, self).__init__(*args, **kwargs)
    self._internal_config = None
    self._paygen_json_gs_path = PAYGEN_JSON_GS_PATH
    self._max_dlc_batch_size = properties.max_dlc_batch_size or None

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

  def get_builder_configs(self, builder_name, **kwargs):
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
        if all(k in b and b[k].lower() == v.lower() for k, v in kwargs.items()):
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
      if (tgt.image_type == common_pb2.IMAGE_TYPE_TEST and
          isinstance(tgt, UnsignedImage_pb2)):
        reqs.append(
            GenerationRequest(src_unsigned_image=tgt, tgt_unsigned_image=tgt,
                              bucket=bucket, verify=verify, dryrun=dryrun,
                              chroot=self.m.cros_sdk.chroot))
        reqs.append(
            GenerationRequest(src_unsigned_image=tgt, tgt_unsigned_image=tgt,
                              bucket=bucket, verify=verify, dryrun=dryrun,
                              chroot=self.m.cros_sdk.chroot, minios=True))
    return reqs

  def get_delta_requests(self, payload_def, src_artifacts, tgt_artifacts,
                         bucket, verify, dryrun):
    """Examine def, source, and target and return list(GenerationRequests).

    If there isn't a matching source and target available, then return [].

    bucket, verify, and dryrun are all used to fill out the GenerationRequest().

    Args:
      payload_def (dict): A singular configuration from pulled config.
      src_artifacts (list[cros_storage.Image]): Available src images.
      tgt_artifacts (list[cros_storage.Image]): Available tgt images.
      bucket (str): The bucket containing the requests (and destination).
      verify (bool): Should we run payload verification.
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

        if isinstance(src, SignedImage_pb2):
          reqs.append(
              GenerationRequest(src_signed_image=src, tgt_signed_image=tgt,
                                bucket=bucket, verify=verify, dryrun=dryrun,
                                chroot=self.m.cros_sdk.chroot))
          reqs.append(
              GenerationRequest(src_signed_image=src, tgt_signed_image=tgt,
                                bucket=bucket, verify=verify, dryrun=dryrun,
                                chroot=self.m.cros_sdk.chroot, minios=True))
        elif isinstance(src, UnsignedImage_pb2):
          # We don't create delta paygens for unsigned recovery images.
          if src.image_type == common_pb2.IMAGE_TYPE_RECOVERY:
            continue  # pragma: nocover
          reqs.append(
              GenerationRequest(src_unsigned_image=src, tgt_unsigned_image=tgt,
                                bucket=bucket, verify=verify, dryrun=dryrun,
                                chroot=self.m.cros_sdk.chroot))
          reqs.append(
              GenerationRequest(src_unsigned_image=src, tgt_unsigned_image=tgt,
                                bucket=bucket, verify=verify, dryrun=dryrun,
                                chroot=self.m.cros_sdk.chroot, minios=True))
        elif isinstance(src, DLCImage_pb2):
          if not self.m.cros_storage.DLCImage.compatible(tgt, src):
            continue  # pragma: nocover
          reqs.append(
              GenerationRequest(src_dlc_image=src, tgt_dlc_image=tgt,
                                bucket=bucket, verify=verify, dryrun=dryrun,
                                chroot=self.m.cros_sdk.chroot))
    return reqs

  def get_full_requests(self, tgt_artifacts, bucket, verify, dryrun):
    """Get the configured full requests for a set of artifacts.

    Args:
      tgt_artifacts (list[cros_storage.Image]): Available tgt images.
      bucket (str): The bucket containing the requests (and destination).
      verify (bool): Should we run payload verification.
      dryrun (bool): Should we not upload resulting artifacts.

    Returns:
      A completed list[GenerationRequest] or [].
    """
    reqs = []
    for tgt in tgt_artifacts:
      if isinstance(tgt, SignedImage_pb2):
        reqs.append(
            GenerationRequest(full_update=True, tgt_signed_image=tgt,
                              bucket=bucket, verify=verify, dryrun=dryrun,
                              chroot=self.m.cros_sdk.chroot))
        reqs.append(
            GenerationRequest(full_update=True, tgt_signed_image=tgt,
                              bucket=bucket, verify=verify, dryrun=dryrun,
                              chroot=self.m.cros_sdk.chroot, minios=True))
      elif isinstance(tgt, UnsignedImage_pb2):
        # We don't create full payloads for unsigned recovery images.
        if tgt.image_type == common_pb2.IMAGE_TYPE_RECOVERY:
          continue  #  pragma: nocover
        reqs.append(
            GenerationRequest(full_update=True, tgt_unsigned_image=tgt,
                              bucket=bucket, verify=verify, dryrun=dryrun,
                              chroot=self.m.cros_sdk.chroot))
        reqs.append(
            GenerationRequest(full_update=True, tgt_unsigned_image=tgt,
                              bucket=bucket, verify=verify, dryrun=dryrun,
                              chroot=self.m.cros_sdk.chroot, minios=True))
      elif isinstance(tgt, DLCImage_pb2):
        reqs.append(
            GenerationRequest(full_update=True, tgt_dlc_image=tgt,
                              bucket=bucket, verify=verify, dryrun=dryrun,
                              chroot=self.m.cros_sdk.chroot))
    return reqs

  def create_au_test_configs(
      self, gen_req, configured_payloads, au_testing_models,
      au_fsi_testing_models,
      delta_test_override=PaygenOrchestratorProperties.RESPECT_CONFIG,
      full_test_override=PaygenOrchestratorProperties.RESPECT_CONFIG):
    """Determine which hardware tests need to be run for the given payload.

    Args:
      gen_req (GenerationRequest): Proto defining the payload-to-be for which to
        find tests.
      configured_payloads (list[dict]): Configs for the payloads we are
        generating and testing.
      au_testing_models (list[str]): The au testing models configured.
      au_fsi_testing_models (list[str]): The au fsi testing models configured.
      delta_test_override (PayloadTestsOverride): Option to override
        the configured delta payload testing policy.
      full_test_override (PayloadTestsOverride): Option to override the
        configured full payload testing policy.

    Returns:
      list[AutoupdateTestConfig]: Test configs that should be
        run for the requested payload.
    """
    # Skip testing entirely for minios.
    if gen_req.minios:
      return []
    # Skip testing for images that aren't unsigned.
    if gen_req.WhichOneof('tgt_image_oneof') != 'tgt_unsigned_image':
      return []
    # Skip testing for images that aren't test images.
    if gen_req.tgt_unsigned_image.image_type != common_pb2.IMAGE_TYPE_TEST:
      return []

    if gen_req.full_update:
      if full_test_override == PaygenOrchestratorProperties.FORCE_NO_TESTS:
        return []
      force_tests = full_test_override == \
          PaygenOrchestratorProperties.FORCE_TESTS
      return self._get_au_test_configs_for_full_payload(gen_req,
                                                        configured_payloads,
                                                        au_testing_models,
                                                        au_fsi_testing_models,
                                                        force_tests=force_tests)
    if delta_test_override == PaygenOrchestratorProperties.FORCE_NO_TESTS:
      return []
    force_tests = delta_test_override == \
        PaygenOrchestratorProperties.FORCE_TESTS
    return self._get_au_test_configs_for_delta_payload(gen_req,
                                                       configured_payloads,
                                                       au_testing_models,
                                                       au_fsi_testing_models,
                                                       force_tests=force_tests)

  def run_paygen_builders(self, paygen_reqs):
    """Launch paygen builders to generate payloads and run configured tests.

    Args:
      paygen_reqs (list[PaygenRequest]): Protos containing the payloads to
        generate and the corresponding tests to launch.

    Returns:
      A list of completed builds.
    """
    paygen_request_dicts = [
        self._create_paygen_request_dict(paygen_req.generation_request,
                                         paygen_req.autoupdate_test_configs)
        for paygen_req in paygen_reqs
    ]
    batches = self._batch_paygen_request_dicts(paygen_request_dicts)
    schedule_requests = [
        self._create_bb_schedule_request(batch) for batch in batches
    ]

    # Define a function to split requests into chunks.
    def _split_large_requests(schedule_requests, max_elements=200):
      """Split large requests into chunks, bb's max is 200 per schedule."""
      split_reqs = []

      min_chunks = math.ceil(len(schedule_requests) / float(max_elements))
      # Very defensively split into [1, max_elements] sized chunks.
      chunk_len = max(
          1,
          min(
              math.ceil(len(schedule_requests) / float(min_chunks)),
              max_elements))

      while schedule_requests:
        split_reqs.append(schedule_requests[0:chunk_len])
        schedule_requests = schedule_requests[chunk_len:]
      return split_reqs

    # Run the buildbucket requests and return the build results.
    split_reqs = _split_large_requests(schedule_requests)
    with self.m.step.nest('running children'):
      builds = []
      for req_chunk in split_reqs:
        builds.extend(
            self.m.buildbucket.schedule(req_chunk, step_name='schedule'))
      self._present_paygen_request_urls(batches, builds)

      build_dict = self.m.buildbucket.collect_builds(
          [b.id for b in builds], timeout=self.paygen_children_timeout_sec,
          step_name='collect', url_title_fn=lambda b: None)
    return [build_dict[b.id] for b in builds]

  def _present_paygen_request_urls(self, paygen_request_batches, builds):
    """Show descriptive URLs about each batch of PaygenRequests.

    Args:
      paygen_request_batches (List[List[PaygenRequest]]): Each element of this
        arg contains a list of PaygenRequests that should be run by a single
        Paygen builder.
      builds: The Paygen builds running the above batches of PaygenRequests,
        listed in the same order as the batches.
    """
    with self.m.step.nest('present') as presentation:
      # Create holder dict.
      title_to_url_dict = collections.OrderedDict()
      # Create all presentational lines.
      for (paygen_requests, build) in zip(paygen_request_batches, builds):
        url_title = self.m.naming.get_paygen_build_title(
            build.id, paygen_requests)
        url_dest = self.m.buildbucket.build_url(build_id=build.id)
        title_to_url_dict[url_title] = url_dest
      # Sort the lines.
      title_to_url_dict = collections.OrderedDict(
          sorted(title_to_url_dict.items(), key=lambda t: t[0].split('|')[1]))
      # Shove them into presentation.
      for (key, value) in title_to_url_dict.items():
        presentation.links[key] = value

  def _get_au_test_configs_for_full_payload(self, gen_req, configured_payloads,
                                            au_testing_models,
                                            au_fsi_testing_models,
                                            force_tests=False):
    """Create AutoupdateTestConfigs for a test-image's full paygen request.

    Args:
      gen_req (GenerationRequest): The delta test payload GenerationRequest
        for which to find tests and schedule.
      configured_payloads (list[dict]): Configs for the payloads we are
        generating and testing.
      au_testing_models (list[str]): The au testing models configured.
      au_fsi_testing_models (list[str]): The au fsi testing models configured.
      force_tests (bool): Whether to override the configured full payload
        testing policy.

    Returns:
      List[AutoupdateTestConfig] corresponding to the GenerationRequest.
    """
    # Get N2N test.
    test_configs = [
        AutoupdateTestConfig(
            src_version=gen_req.tgt_unsigned_image.build.version,
            src_channel=gen_req.tgt_unsigned_image.build.channel,
            delta_type=common_pb2.N2N, applicable_models=au_testing_models)
    ]
    # Get tests from matched configured payloads.
    matching_cfgs = self._match_gen_req_to_configured_payloads(
        gen_req, configured_payloads)
    for cfg in matching_cfgs:
      if cfg.get('full_payload_tests', False) or force_tests:
        fsi = cfg.get('delta_type', '') == 'FSI'
        applicable_models = au_fsi_testing_models if fsi else au_testing_models
        test_configs.append(
            AutoupdateTestConfig(
                src_version=cfg['chrome_os_version'],
                src_channel=cfg['channel'] + '-channel',
                delta_type=common_pb2.DeltaType.Value(cfg['delta_type']),
                applicable_models=applicable_models))
    return test_configs

  def _get_au_test_configs_for_delta_payload(self, gen_req, configured_payloads,
                                             au_testing_models,
                                             au_fsi_testing_models,
                                             force_tests=False):
    """Create AutoupdateTestConfigs for a test-image's delta paygen request.

    Args:
      gen_req (GenerationRequest): The full test payload GenerationRequest
        for which to find tests and schedule.
      configured_payloads (list[dict]): Configs for the payloads we are
        generating and testing.
      au_testing_models (list[str]): The au testing models configured.
      au_fsi_testing_models (list[str]): The au fsi testing models configured.
      force_tests (bool): Whether to override the configured full payload
        testing policy.

    Returns:
      List[AutoupdateTestConfig] corresponding to the GenerationRequest.
    """
    test_configs = []
    # Get N2N test.
    if gen_req.tgt_unsigned_image == gen_req.src_unsigned_image:
      test_configs.append(
          AutoupdateTestConfig(delta_type=common_pb2.N2N,
                               applicable_models=au_testing_models))
    # Get tests from matched configured payloads.
    matching_cfgs = self._match_gen_req_to_configured_payloads(
        gen_req, configured_payloads)
    for cfg in matching_cfgs:
      if cfg['delta_payload_tests'] or force_tests:
        fsi = cfg.get('delta_type', '') == 'FSI'
        applicable_models = au_fsi_testing_models if fsi else au_testing_models
        test_configs.append(
            AutoupdateTestConfig(
                delta_type=common_pb2.DeltaType.Value(cfg['delta_type']),
                applicable_models=applicable_models))
    return test_configs

  def _match_gen_req_to_configured_payloads(self, gen_req, configured_payloads):
    """Determine which paygen configs correlate with the GenerationRequest.

    Match on channel and (for delta payloads) source image version.

    Args:
      gen_req (GenerationRequest): The test payload GenerationRequest for which
        to find tests and schedule.
      configured_payloads (list[dict]): Configs for the payloads we are
        generating and testing.

    Returns:
      list[dict]: Configs matching the GenerationRequest.
    """
    tgt_img = getattr(gen_req, gen_req.WhichOneof('tgt_image_oneof'))
    src_img = getattr(gen_req, gen_req.WhichOneof('src_image_oneof'))
    cfgs = [
        cfg for cfg in configured_payloads
        if self.m.cros_release_util.match_channels(cfg['channel'],
                                                   tgt_img.build.channel)
    ]
    if not gen_req.full_update:
      cfgs = [
          cfg for cfg in cfgs
          if cfg['chrome_os_version'] == src_img.build.version
      ]
    return cfgs

  @staticmethod
  def _create_paygen_request_dict(generation_request, test_requests=None):
    """Create a dict of a PaygenRequest for a Paygen builder.

    Args:
      generation_request (GenerationRequest): Request to generate the desired
        payload.
      test_requests ([AutoupdateTestConfigs]): A list of tests to perform with
        the generated payload.

    Returns:
      A dict of the PaygenRequest for a Paygen builder of the provided
      generation request.
    """
    test_requests = test_requests or []
    return {
        'generation_request':
            MessageToDict(generation_request),
        'autoupdate_test_configs': [
            MessageToDict(x) for x in test_requests or {}
        ]
    }

  def _batch_paygen_request_dicts(self, prds):
    """Separate dicts of PaygenRequests into groups to run together.

    This method separates all the requests into the following batches:
      - DLC requests are all batched together, respecting self._max_dlc_batch_size
        to cap batch sizes.
      - N2N requests are batched alongside the corresponding full payload request,
        because their tests rely on the full images.
      - All other requests are sent through in a batch of 1.

    Args:
      prds (List[dict]): Dicts representing PaygenRequests to run.

    Returns:
      List[List[dict]]: Each element returned contains a group of
          dicts representing PaygenRequests that should be run by the same
          Paygen builder.
    """

    def _gen_req(paygen_request_dict):
      return paygen_request_dict.get('generation_request', {})

    def _tgt_unsigned(paygen_request_dict):
      return _gen_req(paygen_request_dict).get('tgtUnsignedImage', {})

    def _is_dlc(paygen_request_dict):
      return 'tgtDlcImage' in _gen_req(paygen_request_dict)

    def _is_minios(paygen_request_dict):
      return _gen_req(paygen_request_dict).get('minios', False)

    def _is_full_unsigned(paygen_request_dict):
      return 'tgtUnsignedImage' in _gen_req(paygen_request_dict) and _gen_req(
          paygen_request_dict).get('fullUpdate', False)

    def _is_n2n(paygen_request_dict):
      gen_req = _gen_req(paygen_request_dict)
      return 'srcUnsignedImage' in gen_req and 'tgtUnsignedImage' in gen_req and gen_req[
          'srcUnsignedImage'] == gen_req['tgtUnsignedImage']

    # First pass - iterate through all requests and pull out all full unsigned.
    full_image_batches = []
    filtered_prds = []
    for prd in prds:
      if _is_full_unsigned(prd):
        full_image_batches.append([prd])
      else:
        filtered_prds.append(prd)

    # Second pass - create all the batches
    batches = []
    dlcs = []
    for prd in filtered_prds:
      if _is_n2n(prd):
        batched = False
        for full_image_batch in full_image_batches:
          full_image = full_image_batch[0]
          if _tgt_unsigned(full_image) == _tgt_unsigned(prd) and _is_minios(
              full_image) == _is_minios(prd):
            full_image_batch.append(prd)
            batched = True
            break
        if not batched:
          raise StepFailure(
              'N2N request for unsigned image version {} has no corresponding full image request'
              .format(
                  _tgt_unsigned(prd).get('build',
                                         {}).get('version', 'unknown-version')))
      elif _is_dlc(prd):
        dlcs.append(prd)

        # If we have a max DLC batch size, then check to see if we're at that
        # batch limit. If so, cut a batch for the DLCs up to this point.
        if self._max_dlc_batch_size and len(dlcs) == self._max_dlc_batch_size:
          batches.append(dlcs)
          dlcs = []
      else:
        batches.append([prd])

    # Send through all the paired unsigned full + n2ns batches.
    for prd_list in full_image_batches:
      batches.append(prd_list)

    # Send through all the remaining DLC requests. If there is no max batch
    # size, then this will be all DLC requests. If there is a max batch size,
    # then this will be the remaining DLCs that weren't part of the last
    # complete batch.
    if dlcs:
      batches.append(dlcs)

    return batches

  def _create_bb_schedule_request(self, paygen_requests):
    """Create a ScheduleBuildRequest for list of paygen requests.

    Args:
      paygen_requests ([PaygenRequest]): Requests to generate the desired
        payload.

    Returns:
      A ScheduleBuildRequest for a Paygen builder.
    """
    is_staging = self.m.cros_infra_config.is_staging
    bucket = 'staging' if is_staging else 'release'
    builder = 'staging-paygen' if is_staging else 'paygen'
    return self.m.buildbucket.schedule_request(
        bucket=bucket,
        builder=builder,
        properties={'requests': paygen_requests},
        can_outlive_parent=False,
        tags=self.m.buildbucket.tags(
            parent_buildbucket_id=str(self.m.buildbucket.build.id)),
    )
