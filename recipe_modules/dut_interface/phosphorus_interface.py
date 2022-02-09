# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
from collections import namedtuple

from . import dut_interface
from .phosphorus_results import PhosphorusResult, PhosphorusPrejobDUTResponse, PhosphorusTestDUTResponse, PhosphorusFetchCrashDUTResponse

from google.protobuf.timestamp_pb2 import Timestamp
from PB.test_platform import phosphorus


DeviceUnderTest = namedtuple(
    'DeviceUnderTest', ['hostname', 'board', 'model', 'software_dependencies'])
MatchRequest = namedtuple(
    'MatchRequest', ['board', 'model', 'software_dependencies', 'is_primary'])


class MatchDutException(Exception):
  pass


class PhosphorusTestMetadata(dut_interface.DUTTestMetadata):  # pragma: no cover

  def __init__(self, interface, test_id, test, image_storage_server=''):
    """Specific constructor for Phosphorus subclass of DUTTestMetadata

    Args:
    * interface (PhosphorusInterface):
    * test_id (str): The id for a specific test
    * test (skylab_test_runner.Request.Test): The actual test request.
    """
    super(PhosphorusTestMetadata,
          self).__init__(test_id=test_id, test=test,
                         gs_url=interface.logs_gs_url(),
                         image_storage_server=image_storage_server)

    self.load_response = interface.load_skylab_local_state(
        test=test, test_id=self.passthrough_test_id)
    self.phosphorus_config = interface.build_config(
        self.load_response.results_dir)
    # A DeviceUnderTest namedtuple that represents primary DUT.
    self.primary_dut = None
    # A list of DeviceUnderTest namedtuples that represent peer DUTs.
    self.peer_duts = []

  def build_dut_topology(self, prejob):
    """Determine primary dut and peer duts based on a testrunner prejob
    request. In a multi-DUT case, a scheduling unit contains multiple
    DUTs, this method will choice which DUTs will be used and primary/peer
    relations, based on metadata of prejob request and hardware specification
    of DUTs from the scheduling unit.

    Args:
    * prejob (test_platform.skylab_test_runner.Request.Prejob): The prejob
              request with software/hardware attributes and dependencies
              for primary and peer duts.
    """
    # We need to process cases that requested explict model before model
    # agnostic requests, so use two queues here.
    board_queue = []
    model_queue = []
    # Handle primary DUT request first.
    primary = self._create_match_request(prejob, True)
    if primary.model:
      model_queue.append(primary)
    else:
      board_queue.append(primary)
    # Add match request for secondary(peer) DUTs.
    for s_prejob in prejob.secondary_devices:
      req = self._create_match_request(s_prejob, False)
      if req.model:
        model_queue.append(req)
      else:
        board_queue.append(req)
    loaded_duts = self.load_response.dut_topology
    # We need process model queue first because model agnostic(board only)
    # requests have wider selections.
    self._process_match_request(model_queue, loaded_duts)
    self._process_match_request(board_queue, loaded_duts)

  def _create_match_request(self, prejob_request, is_primary):
    return MatchRequest(
        board=prejob_request.software_attributes.build_target.name,
        model=prejob_request.hardware_attributes.model,
        software_dependencies=prejob_request.software_dependencies,
        is_primary=is_primary)

  def _process_match_request(self, match_queue, loaded_duts):
    for req in match_queue:
      dut = self._match_dut(req, loaded_duts)
      if req.is_primary:
        self.primary_dut = dut
      else:
        self.peer_duts.append(dut)

  def _match_dut(self, request, loaded_duts):
    """Helper method to match a DUT request with a hardware resource(hostname)
    based on metadata of the request and the hardware resource(e.g. board).

    Args:
    * request (MatchRequest): Information to match a DUT from loaded_duts.
    * loaded_duts (test_platform.skylab_local_state.load.LoadResponse.dut_topology):
          A list of DUTs metadata that loaded from a DUT or scheduling unit.

    Returns: A DeviceUnderTest namedtuple
    """
    matched_index = -1
    for i, dut in enumerate(loaded_duts):
      # Match based on model if explict model requested as a board
      # can have different models.
      if request.model:
        if request.model == dut.model:
          matched_index = i
          break
      elif request.board == dut.board:
        matched_index = i
        break
    if matched_index > -1:
      dut = loaded_duts.pop(matched_index)
      return DeviceUnderTest(dut.hostname, dut.board, dut.model,
                             request.software_dependencies)
    # We shouldn't hit this point as if a bot is matched to a test, it should
    # contain DUTs that can satisfy all resource requests from the test.
    raise MatchDutException("Failed to match loaded DUT with prejob request.")


class PhosphorusInterface(dut_interface.DUTInterface):  # pragma: no cover

  _MILLISECONDS_IN_SECOND = 1000
  _SECONDS_IN_30_MINUTES = 30 * 60

  def __init__(self, api, properties):
    super(PhosphorusInterface, self).__init__(api, properties)

  def submit_pre_job(self, metadata, max_duration_seconds):
    prejob_properties = self._properties.request.prejob
    # Construct addtional provision targets for multi-DUTs use case.
    addtional_targets = []
    for target in metadata.peer_duts:
      t = phosphorus.prejob.PrejobRequest.ProvisionTarget(
          dut_hostname=target.hostname,
          software_dependencies=target.software_dependencies)
      addtional_targets.append(t)

    with self._api.step.nest('Phosphorus: run prejob'):
      with self._api.context(infra_steps=True):
        prejob_request = phosphorus.prejob.PrejobRequest(
            config=metadata.phosphorus_config,
            dut_hostname=metadata.primary_dut.hostname,
            desired_provisionable_labels=prejob_properties.provisionable_labels,
            existing_provisionable_labels=metadata.load_response
            .provisionable_labels,
            software_dependencies=prejob_properties.software_dependencies,
            use_tls=prejob_properties.use_tls,
            addtional_targets=addtional_targets)
        prejob_request.deadline.MergeFrom(
            self.get_deadline(max_duration_seconds))
        return PhosphorusPrejobDUTResponse(
            metadata.test_id, self._api.phosphorus.prejob(prejob_request))

  def run_test(self, metadata, container_image_info):
    with self._api.step.nest('Phosphorus: run test'):
      run_test_request = phosphorus.runtest.RunTestRequest(
          config=metadata.phosphorus_config,
          dut_hostnames=[metadata.primary_dut.hostname],
          autotest=phosphorus.runtest.RunTestRequest.Autotest(
              name=metadata.test.autotest.name,
              test_args=metadata.test.autotest.test_args,
              image_storage_server=metadata.image_storage_server,
              display_name=metadata.test.autotest.display_name,
              keyvals=self._with_gs_logs_keyval(metadata),
              is_client_test=metadata.test.autotest.is_client_test,
              peer_duts=[dut.hostname for dut in metadata.peer_duts]),
          container_image_info=container_image_info)
      run_test_request.deadline.MergeFrom(self.get_deadline())
      return PhosphorusTestDUTResponse(
          metadata.test_id, self._api.phosphorus.run_test(run_test_request))

  def fetch_crashes(self, metadata,
                    max_duration_seconds=_SECONDS_IN_30_MINUTES):
    crash_response = self._fetch_crashes(metadata, max_duration_seconds)
    try:
      with self._api.step.nest('ensure all crashes were fetched'):
        if len(crash_response.crashes_rtd_only) != 0:
          raise self._api.step.StepFailure("Missing %d crashes" %
                                           len(crash_response.crashes_rtd_only))
    except self._api.step.StepFailure:  # pragma: no cover
      pass

    return PhosphorusFetchCrashDUTResponse(test_id=metadata.test_id,
                                           data=crash_response)

  def _fetch_crashes(self, metadata,
                     max_duration_seconds=_SECONDS_IN_30_MINUTES):
    """ Helper method to fetch crashes with phosphorus

    NOTE: Allow at most 30 minutes for this step

    Args:
    * metadata: Input information relevant to one test in phosphorus.
    * max_duration_seconds: The longest amount of time this test may run.

    Returns: The information for this crash.
    """
    with self._api.step.nest('Phosphorus: fetch crashes'):
      fetch_crashes_request = phosphorus.fetchcrashes.FetchCrashesRequest(
          config=metadata.phosphorus_config,
          dut_hostname=metadata.primary_dut.hostname, upload_crashes=self
          ._properties.request.execution_param.upload_crashes,
          use_staging=False)
      fetch_crashes_request.deadline.MergeFrom(
          self.get_deadline(max_duration_seconds))
      return self._api.phosphorus.fetch_crashes(fetch_crashes_request)

  def upload_to_google_storage(self, metadata):
    with self._api.step.nest('Phosphorus: upload to GS'):
      self._api.phosphorus.upload_to_gs(
          phosphorus.upload_to_gs.UploadToGSRequest(
              config=metadata.phosphorus_config,
              local_directory=metadata.phosphorus_config.task.results_dir,
              gs_directory=metadata.gs_url))

  def upload_to_tko(self, metadata, run_test_response):
    with self._api.step.nest('Phosphorus: upload to TKO'):
      with self._api.context(infra_steps=True):
        self._api.phosphorus.upload_to_tko(
            phosphorus.upload_to_tko.UploadToTkoRequest(
                config=self._build_tko_metadata(metadata, run_test_response)))

  def _build_tko_metadata(self, metadata, run_test_response):
    """Construct a phosphorus.Config specific to upload_to_tko step.

    Unlike other steps, upload_to_tko needs to be pointed to the test-specific
    subdirectory of the overall results directory.

    Args:
    * metadata (PhosphorusTestMetadata): Information for one specific test.
    * run_test_response (PhosphorusTestDUTResponse): Response to a test run.

    Returns: phosphorus.Config.

    Raises:
    * InfraFailure.
    """
    task_results_dir = metadata.phosphorus_config.task.results_dir
    test_results_dir = run_test_response.data.results_dir
    if not test_results_dir.startswith(task_results_dir):
      raise self._api.step.InfraFailure(
          'test results dir %s is not a subdirectory of task results dir %s' %
          (test_results_dir, task_results_dir))

    tko_metadata = phosphorus.common.Config()
    tko_metadata.CopyFrom(metadata.phosphorus_config)
    tko_metadata.task.results_dir = test_results_dir
    return tko_metadata

  def parse_test_results(self, metadata):
    with self._api.step.nest('Phosphorus: get test results'):
      with self._api.context(infra_steps=True):
        return PhosphorusResult(
            self._api.phosphorus.parse(metadata.load_response.results_dir))

  def build_config(self, results_dir):
    """Get a phosphorus config for a give result."""
    return phosphorus.common.Config(
        bot=phosphorus.common.BotEnvironment(
            autotest_dir=self._properties.config.harness.autotest_dir),
        fetch_crashes_step=self._properties.config.fetch_crashes_step,
        log_data_upload_step=self._properties.config.log_data_upload_step,
        prejob_step=self._properties.config.prejob_step,
        task=phosphorus.common.TaskEnvironment(
            results_dir=results_dir, ssp_base_image_name=self._properties.config
            .harness.ssp_base_image_name,
            test_results_dir=os.path.join(results_dir, "autoserv_test")))

  def save_and_seal_skylab_local_state(self, dut_state, metadata):
    with self._api.step.nest('Phosphorus: save local DUT state'):
      self._api.phosphorus.save_and_seal_skylab_local_state(
          dut_state=dut_state, dut_name=metadata.primary_dut.hostname,
          peer_duts=[dut.hostname for dut in metadata.peer_duts])

  def save_skylab_local_state(self, dut_state, metadata):
    with self._api.step.nest(
        'Phosphorus: mark local DUT state: {}'.format(dut_state)):
      self._api.phosphorus.save_skylab_local_state(
          dut_state=dut_state, dut_name=metadata.primary_dut.hostname,
          peer_duts=[dut.hostname for dut in metadata.peer_duts])

  def load_skylab_local_state(self, test, test_id):
    with self._api.step.nest('Phosphorus: load skylab local state'):
      # Check for DUT topology experiment
      use_dut_topo = self.enable_dut_topology_experiment(test)
      with self._api.context(env={'USE_DUT_TOPO': use_dut_topo}):
        return self._api.phosphorus.load_skylab_local_state(test_id=test_id)

  def enable_dut_topology_experiment(self, test):
    # Experiment can be enabled via test/suite allowlists or an explicit flag.
    flag_enabled = self._properties.config.prejob_step.dut_topology_experiment.enabled

    test_allowlist = self._properties.config.prejob_step.dut_topology_experiment.test_allowlist
    suite_allowlist = self._properties.config.prejob_step.dut_topology_experiment.suite_allowlist
    test_allowlisted = test.autotest.name in test_allowlist
    suite_allowlisted = test.autotest.keyvals['suite'] in suite_allowlist

    return flag_enabled or test_allowlisted or suite_allowlisted

  def remove_autotest_results_dir(self):
    with self._api.step.nest('Phosphorus: remove autotest results dir'):
      return self._api.phosphorus.remove_autotest_results_dir()

  def read_dut_hostname(self):
    if not self._dut_hostname:
      self._dut_hostname = self._read_dut_hostname(self._api)
    return self._dut_hostname

  @staticmethod
  def _read_dut_hostname(api):
    return api.phosphorus.read_dut_hostname()

  def get_deadline(self, max_duration_seconds=None):
    """Determine the deadline for this build.

    Args:
    * max_duration_seconds (int): The maximum duration for this job.

    Returns:
      google.protobuf.Timestamp instance.
    """
    build_timeout = self._api.buildbucket.build.execution_timeout
    build_deadlines = [self._build_timestamp(build_timeout.seconds)]

    if self._properties.request.HasField('deadline'):
      build_deadlines.append(self._properties.request.deadline)

    if max_duration_seconds:
      build_deadlines.append(self._build_timestamp(max_duration_seconds))

    # Use the earlier of the three deadlines: one of the two globally
    # configured max durations or the request's deadline (if provided).
    return self._min_timestamp(build_deadlines)

  def _build_timestamp(self, seconds_from_now):
    """Builds a timestamp proto representing now + seconds_from_now.

    Args:
    * seconds_from_now (int): The maximum duration for this job.

    Returns:
      google.protobuf.Timestamp instance.
    """
    now_seconds = self._api.time.ms_since_epoch() / self._MILLISECONDS_IN_SECOND
    return Timestamp(seconds=now_seconds + seconds_from_now)

  @staticmethod
  def _min_timestamp(timestamps_list):
    """Gets the minimum timestamp from a list of Timestamps.

    Args:
    * timestamps_list (List[Timestamp]): List of candidate timestamps.

    Returns:
      google.protobuf.Timestamp instance
    """
    assert len(timestamps_list) > 0
    global_minimum = timestamps_list[0]
    for local_minimum in timestamps_list[1:]:
      if local_minimum.seconds < global_minimum.seconds:
        global_minimum = local_minimum
    return global_minimum

  @staticmethod
  def _with_gs_logs_keyval(metadata):
    """Gets the keyval from autotest and populates it with the latest URLs.

    This keyval is required for stainless' test results view to link to the
    test logs.
    - Autoserv drops keyvals in a file in the logs directory
    - tko/parse parses that file and injects keyvals in the TKO database
    - Stainless table builder extracts this particular keyval and uses the value
      to link to the archived logs.

    Args:
    * metadata (PhosphorusTestMetadata): Input information relevant to one
    test in phosphorus.

    Returns: The updated keyvals as a dict.
    """
    keyvals = metadata.test.autotest.keyvals
    keyvals['synchronous_log_data_url'] = metadata.gs_url
    keyvals['synchronous_log_data_stainless_url'] = metadata.stainless_logs_url
    return keyvals

  def logs_gs_url(self):
    gs_root = self._properties.config.output.log_data_gs_root
    now = self._api.time.utcnow()
    return '%s/%s/%s' % (gs_root, now.date().isoformat(),
                         self._api.uuid.random())

  def get_results_directory(self, metadata):
    return metadata.load_response.results_dir

  def _get_image_storage_server(self):
    """Extract the first chromeos_build_gcs_bucket from requet's prejob or ''.
    """
    iss = ''
    sw_deps = self._properties.request.prejob.software_dependencies
    for sw_dep in sw_deps:
      if sw_dep.WhichOneof('dep') == 'chromeos_build_gcs_bucket':
        iss = sw_dep.chromeos_build_gcs_bucket
        break
    if iss and not iss.startswith('gs://'):
      iss = 'gs://' + iss
    return iss

  def build_test_metadata(self, test_id, test):
    metadata = PhosphorusTestMetadata(self, test_id, test,
                                      self._get_image_storage_server())
    try:
      metadata.build_dut_topology(self._properties.request.prejob)
    except MatchDutException:
      raise self._api.step.InfraFailure(
          "Failed to match loaded DUT with prejob request.")
    return metadata

  @staticmethod
  def build_empty_result():
    return PhosphorusResult()

  @staticmethod
  def build_aborted_prejob_response(test_metadata):
    return PhosphorusPrejobDUTResponse.build_aborted_response(
        test_metadata.test_id)
