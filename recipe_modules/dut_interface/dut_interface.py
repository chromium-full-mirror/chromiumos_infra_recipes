# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Plugable interface for the DUT."""

import time

from abc import ABCMeta, abstractmethod

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2


class DUTTestMetadata():  # pragma: no cover
  __metaclass__ = ABCMeta

  DUMMY_TEST_ID = 'original_test'

  def __init__(self, test_id, test, gs_url, image_storage_server='',
               invocation_id=''):
    """Holds metadata relevant to one specific test. Passable to DutInterface

    Args:
    * test_id (str): The id for a specific test
    * test (skylab_test_runner.Request.Test): The actual test request.
    * gs_url (str): The url to google cloud storage for this test.
    * image_storage_server (str): The url for the image storage for the test.
        e.g. gs://chromeos-releases-test
    * invocation_id (str): Invocation id of the test run.
    """
    self.test_id = test_id
    # TODO: Remove this once all tests have IDs
    # The dummy test ID gets replaced with an empty string here because
    # the test ID gets included in the results directory. By sending through
    # an empty string, the results directory won't be changed for the 'test'
    # field.
    self.passthrough_test_id = '' if test_id == self.DUMMY_TEST_ID else test_id
    self.test = test
    self.gs_url = gs_url
    self.testhaus_logs_url = self._parse_logs_url(self.gs_url, invocation_id)
    self.image_storage_server = image_storage_server

  @staticmethod
  def _parse_logs_url(gs_dir, invocation_id=''):
    """Return testhaus logs URL for the given gs URL.

    Args:
    * gs_dir (str): The Google Storage directory.
    * invocation_id (str): The invocation id of the test run.

    Returns:
      str: URL to logs in testhaus.

    Raises:
      AssertionError if gs_dir does not start with `gs://`
    """
    gs_prefix = 'gs://'
    template_url = (
        'https://tests.chromeos.goog/p/chromeos/logs/unified/{logs_path}')
    assert gs_dir.startswith(gs_prefix), '{} should start with {}'.format(
        gs_dir, gs_prefix)

    logs_path = 'invocations/' + invocation_id if invocation_id else gs_dir[
        len(gs_prefix):]
    return template_url.format(logs_path=logs_path)


class DUTInterface():  # pragma: no cover
  __metaclass__ = ABCMeta

  def __init__(self, api, properties):
    """Adapter interface to a Device Under Test.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe API.
    * properties (TestRunnerProperties): Input properties to the recipe.
    """
    self._api = api
    self._properties = properties
    self._dut_hostname = self._read_dut_hostname(self._api)

  @abstractmethod
  def submit_pre_job(self, metadata, max_duration_seconds):
    """Submits a Prejob execution on the DUT.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * max_duration_seconds (int): The longest amount of time this test may run.

    Returns:
      dut_results.DUTPrejobResponse: The prejob results.

    Raises:
      * api.test.StepFailure If prejob fails.
    """

  @abstractmethod
  def run_test(self, metadata, container_image_info):
    """Submits a test execution on the DUT.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * container_image_info (ContainerImageInfo): If set, info on a Docker
    container for use by the DUTInterface. For example, autoserv may be run by
    the container instead of the host.

    Returns:
      dut_results.DUTTestResponse: The test results.

    Raises:
      * api.test.StepFailure If test fails.
    """

  @abstractmethod
  def fetch_crashes(self, metadata, max_duration_seconds):
    """Retrieves crash information in case of a crash.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * max_duration_seconds (int): The longest amount of time this test may run.

    Returns:
      dut_results.DUTFetchCrashResponse: The crash information.

    Raises:
      * api.test.StepFailure If test fails.
    """

  @abstractmethod
  def upload_to_google_storage(self, metadata):
    """Uploads test information to Google Storage for current test.

    Args:
      metadata (DUTTestMetadata): Input information relevant to one test.
    """

  @abstractmethod
  def upload_to_tko(self, metadata, run_test_response):
    """Uploads test information to TKO for current test.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * run_test_response (DUTTestResponse): The response to the test run.

    Raises:
    * InfraFailure.
    """

  @abstractmethod
  def upload_to_rdb(self, metadata, run_test_response, force_current_realm,
                    skip_board_model_check):
    """Uploads test results to resultDB.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test job.
    * run_test_response (DUTTestResponse): The response to the test run.
    * force_current_realm (Boolean): Whether to force publishing to rdb in the current realm
    * skip_board_model_check (Boolean): Whether to skip verifying board-model realm exists

    Raises:
    * InfraFailure.
    """

  @abstractmethod
  def parse_test_results(self, metadata):
    """For one specific test, get the test results in the form of DUTResult.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.

    Returns:
      dut_results.DUTResult: Constructed DUTResult for a specific test.

    Raises:
    * InfraFailure.
    """

  @abstractmethod
  def save_and_seal_skylab_local_state(self, dut_state, metadata,
                                       repair_requests=None):
    """Save and seal skylab local state on DUT.

    Args:
    * dut_state (str): The desired state.
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * repair_requests (array): Requests to enforce repair actions.
    """

  @abstractmethod
  def save_skylab_local_state(self, dut_state, metadata):
    """Save skylab local state on DUT.

    Args:
    * dut_state (str): The desired state.
    * metadata (DUTTestMetadata): Input information relevant to one test.
    """

  @abstractmethod
  def load_skylab_local_state(self, test, test_id):
    """Get skylab local state from DUT for specific test.

    Args:
    * test (skylab_test_runner.Request.Test): The actual test request.
    * test_id (str): The desired test to pull state from.

    Returns:
      skylab_local_state.LoadResponse
    """

  def read_dut_hostname(self):
    """Read cached hostname for DUT.

    Returns:
      str
    """
    return self._dut_hostname

  @staticmethod
  @abstractmethod
  def _read_dut_hostname(api):
    """Retrieve the DUT hostname dynamically.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe API.

    Returns:
      str
    """

  @abstractmethod
  def build_test_metadata(self, test_id, test, autotest_keyvals,
                          cft_test_request):
    """Get the test metadata for the designated single test for this interface.

    Args:
    * test_id (str): The id for the current test.
    * test (skylab_test_runner.Request.Test): The actual test request for the
    current test.
    * autotest_keyvals (dict): Autotest keyvals map.
    * cft_test_request (skylab_test_runner.test_platform.CftTestRequest): cft test request.
    Only called in the cft workflow for cros-tool-runner, not phosphorus.

    Returns:
      DUTTestMetadata: Compact metadata representing the single test for this
      interface.
    """

  @abstractmethod
  def get_results_directory(self, metadata):
    """Retrieves the directory whereupon results are deposited.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.

    Returns:
      str
    """

  @staticmethod
  @abstractmethod
  def build_aborted_prejob_response(test_metadata):
    """Get a prejob response representation for an aborted job.

    Args:
    * test_metadata (DUTTestMetadata):  Input information relevant to one test.

    Returns:
      dut_results.DUTPrejobResponse
    """

  @staticmethod
  @abstractmethod
  def build_empty_result():
    """Get a DUT result without items in it (useful for building).

    Returns:
      dut_results.DUTResult
    """

  @abstractmethod
  def process_test_responses(self, test_responses):
    """process test responses from run_test.

    Args:
    * test_responses (object): test responses from run_test.

    Returns:
      processed test responses: (test_responses_for_output_props, test_response_for_result_uploading)
    """

  def _format_time(self, given_time):
    """Uniformally format time into a human readable form.

    Args:
      * time (float): Float time in time.time() form.
      * step (StepPresentation): The step to add this log under.

    Return:
      string: locally formatting time in the form of (day_of_week month day
      hour:time:second year)
    """
    utctime = time.gmtime(given_time)
    return time.asctime(utctime)

  def _get_context_deadline(self, limit_seconds, step):
    """Form a deadline to be used by recipe_engine/context.

    Args:
      * limit_seconds (int): Number of seconds that the process will be allowed to
        run.
      step (StepPresentation): The step to add this log under.

    Returns:
      * sections_pb2.Deadline: A luci representation of a deadline. Includes a UTC
        time and a grace period.
    """
    current_time = self._api.time.time()

    # Make the deadline
    deadline = sections_pb2.Deadline()
    deadline.soft_deadline = current_time + limit_seconds
    deadline.grace_period = 30.0

    # Grab the builder deadline
    builder_deadline = self._api.context.deadline.soft_deadline

    # Set deadline to which ever value is sooner
    deadline.soft_deadline = builder_deadline if builder_deadline < deadline.soft_deadline else deadline.soft_deadline


    # Add deadline information to the step logs.
    step.logs[
        'deadline information'] = 'start: %s\nend: %s\ntotal_seconds: %s\n' % (
            self._format_time(current_time),
            self._format_time(deadline.soft_deadline), str(limit_seconds))

    return deadline

  def is_within_deadline(self):
    """Determines if a test is within deadline.

    If the properties have a deadline, and it is exceded set the step to
    failed and return False, else return True.

    Returns:
      bool: False for exceeded, True for not.
    """
    with self._api.step.nest('DUTInterface: check request deadline') as step:
      if self._properties.request.HasField('deadline'):
        deadline = self._properties.request.deadline
        current_time = self._api.time.time()
        if deadline.seconds < current_time:
          step.status = self._api.step.FAILURE
          return False
      return True
