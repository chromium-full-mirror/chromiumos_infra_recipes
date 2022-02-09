# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Plugable interface for the DUT."""

from abc import ABCMeta, abstractmethod


class DUTTestMetadata(object):  # pragma: no cover
  __metaclass__ = ABCMeta

  DUMMY_TEST_ID = 'original_test'

  def __init__(self, test_id, test, gs_url, image_storage_server=''):
    """Holds metadata relevant to one specific test. Passable to DutInterface

    Args:
    * test_id (str): The id for a specific test
    * test (skylab_test_runner.Request.Test): The actual test request.
    * gs_url (str): The url to google cloud storage for this test.
    * image_storage_server (str): The url for the image storage for the test.
        e.g. gs://chromeos-releases-test
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
    self.stainless_logs_url = self._parse_stainless_logs_url(self.gs_url)
    self.image_storage_server = image_storage_server

  @staticmethod
  def _parse_stainless_logs_url(gs_dir):
    """Return a stainless equivalent URL to the given gs URL.

    Args:
    * gs_dir (str): The Google Storage directory.

    Returns:
      str: Stainless URL

    Raises:
      AssertionError if gs_dir does not start with `gs://`
    """
    assert gs_dir.startswith('gs://'), "{} should start with gs://".format(
        gs_dir)
    return 'https://stainless.corp.google.com/browse/%s' % gs_dir[len('gs://'):]


class DUTInterface(object):  # pragma: no cover
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
    pass

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
    pass

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
    pass

  @abstractmethod
  def upload_to_google_storage(self, metadata):
    """Uploads test information to Google Storage for current test.

    Args:
      metadata (DUTTestMetadata): Input information relevant to one test.
    """
    pass

  @abstractmethod
  def upload_to_tko(self, metadata, run_test_response):
    """Uploads test information to TKO for current test.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.
    * run_test_response (DUTTestResponse): The response to the test run.

    Raises:
    * InfraFailure.
    """
    pass

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
    pass

  @abstractmethod
  def save_and_seal_skylab_local_state(self, dut_state, metadata):
    """Save and seal skylab local state on DUT.

    Args:
    * dut_state (str): The desired state.
    * metadata (DUTTestMetadata): Input information relevant to one test.
    """
    pass

  @abstractmethod
  def save_skylab_local_state(self, dut_state, metadata):
    """Save skylab local state on DUT.

    Args:
    * dut_state (str): The desired state.
    * metadata (DUTTestMetadata): Input information relevant to one test.
    """
    pass

  @abstractmethod
  def load_skylab_local_state(self, test, test_id):
    """Get skylab local state from DUT for specific test.

    Args:
    * test (skylab_test_runner.Request.Test): The actual test request.
    * test_id (str): The desired test to pull state from.

    Returns:
      skylab_local_state.LoadResponse
    """
    pass

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
    pass

  @abstractmethod
  def build_test_metadata(self, test_id, test):
    """Get the test metadata for the designated single test for this interface.

    Args:
    * test_id (str): The id for the current test.
    * test (skylab_test_runner.Request.Test): The actual test request for the
    current test.

    Returns:
      DUTTestMetadata: Compact metadata representing the single test for this
      interface.
    """
    pass

  @abstractmethod
  def get_results_directory(self, metadata):
    """Retrieves the directory whereupon results are deposited.

    Args:
    * metadata (DUTTestMetadata): Input information relevant to one test.

    Returns:
      str
    """
    pass

  @staticmethod
  @abstractmethod
  def build_aborted_prejob_response(test_metadata):
    """Get a prejob response representation for an aborted job.

    Args:
    * test_metadata (DUTTestMetadata):  Input information relevant to one test.

    Returns:
      dut_results.DUTPrejobResponse
    """
    pass

  @staticmethod
  @abstractmethod
  def build_empty_result():
    """Get a DUT result without items in it (useful for building).

    Returns:
      dut_results.DUTResult
    """
    pass

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
          step.presentation.status = self._api.step.FAILURE
          return False
      return True
