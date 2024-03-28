# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""CrosToolRunner Result objects for crostoolrunner_interface."""

import base64
import zlib

from RECIPE_MODULES.chromeos.dut_interface import dut_results

from PB.chromiumos.test.api.cros_provision_cli import CrosProvisionResponse
from PB.chromiumos.test.api.provision_service import InstallFailure
from PB.chromiumos.test.api.test_case_result import TestCaseResult


class InvalidPrejobResponseStateException(Exception):
  pass


class InvalidTestResponseStateException(Exception):
  pass


class CrosToolRunnerPrejobDUTResponse(dut_results.DUTPrejobResponse
                                     ):  # pragma: no cover
  PREJOB_FAILURE = 'failure'

  def is_failure(self):
    """Whether the job has failed.

    Returns: bool
    """
    return self.get_state_name() == self.PREJOB_FAILURE

  @staticmethod
  def build_aborted_response(test_id):
    """Create a DUTPrejobResponse for an aborted job.

    Args:
    * test_id (str): The unique identifier for a single test.

    Returns: DUTPrejobResponse
    """
    return CrosToolRunnerPrejobDUTResponse(
        test_id=test_id, data=CrosProvisionResponse(
            failure=InstallFailure(
                reason=InstallFailure.Reason.REASON_PROVISIONING_TIMEDOUT)))

  def get_state_name(self):
    """Get the state name for this job.

    Returns: str
    """
    state = self.data.WhichOneof('outcome')
    if state:
      return state.lower()
    raise InvalidPrejobResponseStateException(
        'No outcome found in provision response.')


class CrosToolRunnerTestDUTResponse(dut_results.DUTTestResponse
                                   ):  # pragma: no cover
  TEST_FAILURE = 'fail'
  TEST_SKIPPED = 'skip'
  TEST_NOT_RUN = 'not_run'
  TEST_CRASH = 'crash'

  def is_failure(self):
    """Whether the job has failed.

    Returns: bool
    """
    return self.get_state_name() in (self.TEST_FAILURE, self.TEST_NOT_RUN,
                                     self.TEST_CRASH)

  def is_skipped(self):
    """Whether the job was skipped.

    Returns: bool
    """
    return self.get_state_name() == self.TEST_SKIPPED

  @staticmethod
  def build_aborted_response(test_id):
    """Create a DUTTestResponse for an aborted job.

    Args:
    * test_id (str): The unique identifier for a single test.

    Returns: DUTTestResponse
    """
    return CrosToolRunnerTestDUTResponse(
        test_id=test_id, data=TestCaseResult(abort=TestCaseResult.Abort()))

  def get_state_name(self):
    """Get the state name for this job.

    Returns: str
    """
    state = self.data.WhichOneof('verdict')
    if state:
      return state.lower()
    raise InvalidTestResponseStateException(
        'No verdict found in test case result.')


class CrosToolRunnerResult(dut_results.DUTResult):  # pragma: no cover

  def __init__(self, data=None):
    """CrosToolRunner metatada container for all test responses.

    Stores within:
    * dut_results.DUTTestResponse
    * crostoolrunner_interface.PrejobResponsesTuple

    Args:
    * data: Not used for now.
    """
    super().__init__(data)
    self.gs_url = None
    self.testhaus_url = None

  def is_failure(self):
    """Whether this job has failed.

    Returns: bool
    """
    if self.prejob_response.any_provision_failed:
      return True
    for test_response in self.test_responses:
      if test_response.is_failure():
        return True
    return False

  def update_log_urls(self, metadata):
    """Update the result to contain the up-to-date log urls in metadata.

    Args:
    * metadata (dut_interface.DUTTestMetadata): Unique information for a
    single test.
    """
    self.gs_url = metadata.gs_url
    self.testhaus_url = metadata.testhaus_logs_url

  def get_testhaus_log_url(self):
    """Retrieve the url for Testhaus logs.

    Returns: str
    """
    return self.testhaus_url

  def get_dut_state(self):
    """Retrieves the state of this dut.

    Returns: str
    """
    raise NotImplementedError

  def is_test_incomplete(self):
    """Whether this test's state is incomplete.

    Returns: bool
    """
    raise NotImplementedError

  def prejob_failed(self):
    """Whether the prejob has a failure.

    Returns: bool
    """
    return self.prejob_response.any_provision_failed

  def get_prejob_steps(self):
    """Get the prejob steps executed.

    Returns: List[dut_results.DUTPrejobResponse]
    """
    return self.prejob_response.prejob_dut_responses

  def get_test_results(self):
    """Retrieves the test results in the form of (id, result).

    Returns: List[dut_results.DUTTestResponse]
    """
    return self.test_responses

  def serialize(self):
    """Returns a serialized representation of the result data.

    Returns: str
    """
    return base64.b64encode(zlib.compress(self.data.SerializeToString()))

  def add_prejob_response(self, response):
    """Adds a prejob response to this result (overwrites existing).

    Args:
    * response (DUTPrejobResponse): response to a prejob to add to this
    overall response.
    """
    self.prejob_response = response

  def add_test_response(self, response):
    """Adds a test response to this result (adds to list).

    Args:
    * response (DUTTestResponse): response to a test to add to this overall
    response.
    """
    if response:
      self.test_responses.extend(response.test_dut_responses or [])

  def add_result(self, test_id, result):
    """Adds a result to this response (updates all values accordingly).

    Args:
    * result (DUTResult): Overall result to add to overall response.
    """
    del test_id

    if result:
      self.data = result.data
      self.gs_url = result.gs_url
      self.testhaus_url = result.testhaus_url
      self.prejob_response = result.prejob_response
      self.test_responses.extend(result.test_responses)
