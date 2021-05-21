# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from . import dut_interface
from .phosphorus_results import *

from google.protobuf.timestamp_pb2 import Timestamp
from PB.test_platform import phosphorus, skylab_test_runner, skylab_local_state


class PhosphorusTestMetadata(dut_interface.DUTTestMetadata):  # pragma: no cover

  def __init__(self, interface, test_id, test):
    """Specific constructor for Phosphorus subclass of DUTTestMetadata

    Args:
    * interface (PhosphorusInterface):
    * test_id (str): The id for a specific test
    * test (skylab_test_runner.Request.Test): The actual test request.
    """
    super(PhosphorusTestMetadata, self).__init__(test_id=test_id, test=test,
                                                 gs_url=interface.logs_gs_url())
    self.load_response = interface.load_skylab_local_state(
        test_id=self.passthrough_test_id)
    self.phosphorus_config = interface.build_config(
        self.load_response.results_dir)


class PhosphorusInterface(dut_interface.DUTInterface):  # pragma: no cover

  _MILLISECONDS_IN_SECOND = 1000
  _SECONDS_IN_30_MINUTES = 30 * 60

  def __init__(self, api, properties):
    super(PhosphorusInterface, self).__init__(api, properties)

  def submit_pre_job(self, metadata, max_duration_seconds):
    prejob_properties = self._properties.request.prejob

    with self._api.step.nest('Phosphorus: run prejob') as step:
      with self._api.context(infra_steps=True):
        prejob_request = phosphorus.prejob.PrejobRequest(
            config=metadata.phosphorus_config,
            dut_hostname=self.read_dut_hostname(),
            desired_provisionable_labels=prejob_properties.provisionable_labels,
            existing_provisionable_labels=metadata.load_response
            .provisionable_labels,
            software_dependencies=prejob_properties.software_dependencies,
            use_tls=prejob_properties.use_tls)
        prejob_request.deadline.MergeFrom(
            self.get_deadline(max_duration_seconds))
        return PhosphorusPrejobDUTResponse(
            metadata.test_id, self._api.phosphorus.prejob(prejob_request))

  def run_test(self, metadata):
    with self._api.step.nest('Phosphorus: run test') as step:
      run_test_request = phosphorus.runtest.RunTestRequest(
          config=metadata.phosphorus_config,
          dut_hostnames=[self.read_dut_hostname()],
          autotest=phosphorus.runtest.RunTestRequest.Autotest(
              name=metadata.test.autotest.name,
              test_args=metadata.test.autotest.test_args,
              display_name=metadata.test.autotest.display_name,
              keyvals=self._with_gs_logs_keyval(metadata),
              is_client_test=metadata.test.autotest.is_client_test,
          ))
      run_test_request.deadline.MergeFrom(self.get_deadline())
      return PhosphorusTestDUTResponse(
          metadata.test_id, self._api.phosphorus.run_test(run_test_request))

  def fetch_crashes(self, metadata,
                    max_duration_seconds=_SECONDS_IN_30_MINUTES):
    crash_response = self._fetch_crashes(metadata, max_duration_seconds)
    try:
      with self._api.step.nest('ensure all crashes were fetched') as step:
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
    with self._api.step.nest('Phosphorus: fetch crashes') as step:
      fetch_crashes_request = phosphorus.fetchcrashes.FetchCrashesRequest(
          config=metadata.phosphorus_config,
          dut_hostname=self.read_dut_hostname(), upload_crashes=self._properties
          .request.execution_param.upload_crashes, use_staging=False)
      fetch_crashes_request.deadline.MergeFrom(
          self.get_deadline(max_duration_seconds))
      return self._api.phosphorus.fetch_crashes(fetch_crashes_request)

  def upload_to_google_storage(self, metadata):
    with self._api.step.nest('Phosphorus: upload to GS') as step:
      self._api.phosphorus.upload_to_gs(
          phosphorus.upload_to_gs.UploadToGSRequest(
              config=metadata.phosphorus_config,
              local_directory=metadata.phosphorus_config.task.results_dir,
              gs_directory=metadata.gs_url))

  def upload_to_tko(self, metadata, run_test_response):
    with self._api.step.nest('Phosphorus: upload to TKO') as step:
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
    with self._api.step.nest('Phosphorus: get test results') as step:
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

  def save_and_seal_skylab_local_state(self, dut_state):
    with self._api.step.nest('Phosphorus: save local DUT state'):
      self._api.phosphorus.save_and_seal_skylab_local_state(dut_state)

  def save_skylab_local_state(self, dut_state):
    with self._api.step.nest(
        'Phosphorus: mark local DUT state: {}'.format(dut_state)):
      self._api.phosphorus.save_skylab_local_state(dut_state)

  def load_skylab_local_state(self, test_id):
    with self._api.step.nest('Phosphorus: load skylab local state'):
      return self._api.phosphorus.load_skylab_local_state(test_id=test_id)

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

  def build_test_metadata(self, test_id, test):
    return PhosphorusTestMetadata(self, test_id, test)

  @staticmethod
  def build_empty_result():
    return PhosphorusResult()

  @staticmethod
  def build_aborted_prejob_response(test_metadata):
    return PhosphorusPrejobDUTResponse.build_aborted_response(
        test_metadata.test_id)
