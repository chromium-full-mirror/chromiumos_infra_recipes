# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Result objects for dut_interface."""

from abc import ABCMeta
from abc import abstractmethod

from google.protobuf import json_format


class DUTPrejobResponse():  # pragma: no cover
  __metaclass__ = ABCMeta

  def __init__(self, test_id, data):
    """Response for a DUT pre-job submit.

    Args:
    * test_id (str): Test identifier for a single test.
    * data (Any): Specific metadata for a response.
    """
    self.data = data
    self.test_id = test_id

  @abstractmethod
  def is_failure(self):
    """Whether the job has failed.

    Returns: bool
    """

  @staticmethod
  @abstractmethod
  def build_aborted_response(test_id):
    """Create a DUTPrejobResponse for an aborted job.

    Args:
    * test_id (str): The unique identifier for a single test.

    Returns: DUTPrejobResponse
    """

  @abstractmethod
  def get_state_name(self):
    """Get the state name for this job.

    Returns: str
    """


class DUTTestResponse():  # pragma: no cover
  __metaclass__ = ABCMeta

  def __init__(self, test_id, data):
    """Response for a test.

    Args:
    * test_id (str): Unique identifier for a single test.
    * data (Any): Specific metadata for the response.
    """
    self.data = data
    self.test_id = test_id

  @abstractmethod
  def is_failure(self):
    """Whether the job has failed.

    Returns: bool
    """

  @abstractmethod
  def is_skipped(self):
    """Whether the job was skipped.

    Returns: bool
    """

  @staticmethod
  @abstractmethod
  def build_aborted_response(test_id):
    """Create a DUTTestResponse for an aborted job.

    Args:
    * test_id (str): The unique identifier for a single test.

    Returns: DUTTestResponse
    """

  @abstractmethod
  def get_state_name(self):
    """Get the state name for this job.

    Returns: str
    """


class DUTFetchCrashResponse():  # pragma: no cover
  __metaclass__ = ABCMeta

  def __init__(self, test_id, data):
    """Response for a fetch crashes call.

    Args:
    * test_id (str): Unique identifier for a single test.
    * data (Any): Specific metadata for the response.
    """
    self.data = data
    self.test_id = test_id


class DUTResult():  # pragma: no cover
  __metaclass__ = ABCMeta

  def __init__(self, data):
    """Metatada container for all test responses (contains prejob, test, etc).

    Args:
    * data: Specific metadata for a result response.
    """
    self.data = data
    self.test_responses = []
    self.prejob_response = None

  def has_any_failures(self):
    """Whether the job or any underlying step(prejob + test) has failed.

    Returns: bool
    """
    return self.is_failure() or self.prejob_failed() or self.test_failed()

  def prejob_failed(self):
    """Whether the prejob has a failure.

    Returns: bool
    """
    return self.prejob_response.is_failure() if self.prejob_response else False

  def test_failed(self):
    """Whether any test has a failure.

    Returns: bool
    """
    for test_response in self.test_responses:
      if test_response.is_failure():
        return True
    return False

  @abstractmethod
  def is_failure(self):
    """Whether this job has failed.

    Returns: bool
    """

  @abstractmethod
  def update_log_urls(self, metadata):
    """Update the result to contain the up-to-date log urls in metadata.

    Args:
    * metadata (dut_interface.DUTTestMetadata): Unique information for a
    single test.
    """

  @abstractmethod
  def get_testhaus_log_url(self):
    """Retrieve the URL for Testhaus logs

    Returns: str
    """

  @abstractmethod
  def get_prejob_steps(self):
    """Get the prejob steps executed.

    Returns: List[Result.Prejob.Step]
    """

  @abstractmethod
  def is_test_incomplete(self):
    """Whether this test's state is incomplete.

    Returns: bool
    """

  @abstractmethod
  def get_test_results(self):
    """Retrieves the test results in the form of (id, result).

    Returns: Iterable[(str, Result.Autotest)]
    """

  @abstractmethod
  def serialize(self):
    """Returns a serialized representation of the result data.

    Returns: str
    """

  @abstractmethod
  def add_prejob_response(self, response):
    """Adds a prejob response to this result (overwrites existing).

    Args:
    * response (DUTPrejobResponse): response to a prejob to add to this
    overall response.
    """

  @abstractmethod
  def add_test_response(self, response):
    """Adds a test response to this result (adds to list).

    Args:
    * response (DUTTestResponse): response to a test to add to this overall
    response.
    """

  @abstractmethod
  def add_result(self, test_id, result):
    """Adds a result to this response (updates all values accordingly).

    Args:
    * result (DUTResult): Overall result to add to overall response.
    """

  @abstractmethod
  def get_dut_state(self):
    """Retrieves the state of this dut.

    Returns: str
    """

  def get_failed_tests(self):
    """Retrieves all tests which have a failed status.

    Returns: List[DUTTestResponse]
    """
    result = []
    for run_test in self.test_responses:
      if run_test.is_failure():
        result.append(run_test)

    return result

  def to_json(self):
    """Returns the response in printable json format.

    Returns: dict
    """
    return json_format.MessageToJson(self.data)
