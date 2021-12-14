# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Result objects for dut_interface."""

from abc import ABCMeta, abstractmethod

from google.protobuf import json_format


class DUTPrejobResponse(object):  # pragma: no cover
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
    pass

  @staticmethod
  @abstractmethod
  def build_aborted_response(test_id):
    """Create a DUTPrejobResponse for an aborted job.

    Args:
    * test_id (str): The unique identifier for a single test.

    Returns: DUTPrejobResponse
    """
    pass

  @abstractmethod
  def get_state_name(self):
    """Get the state name for this job.

    Returns: str
    """
    pass


class DUTTestResponse(object):  # pragma: no cover
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
    pass

  @staticmethod
  @abstractmethod
  def build_aborted_response(test_id):
    """Create a DUTTestResponse for an aborted job.

    Args:
    * test_id (str): The unique identifier for a single test.

    Returns: DUTTestResponse
    """
    pass

  @abstractmethod
  def get_state_name(self):
    """Get the state name for this job.

    Returns: str
    """
    pass


class DUTFetchCrashResponse(object):  # pragma: no cover
  __metaclass__ = ABCMeta

  def __init__(self, test_id, data):
    """Response for a fetch crashes call.

    Args:
    * test_id (str): Unique identifier for a single test.
    * data (Any): Specific metadata for the response.
    """
    self.data = data
    self.test_id = test_id


class DUTResult(object):  # pragma: no cover
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
    pass

  @abstractmethod
  def update_log_urls(self, metadata):
    """Update te result to contain the up-to-date log urls in metadata.

    Args:
    * metadata (dut_interface.DUTTestMetadata): Unique information for a
    single test.
    """
    pass

  @abstractmethod
  def get_stainless_log_url(self):
    """Retrieve the url for stainless logs

    Returns: str
    """
    pass

  @abstractmethod
  def get_prejob_steps(self):
    """Get the prejob steps executed.

    Returns: List[Result.Prejob.Step]
    """
    pass

  @abstractmethod
  def is_test_incomplete(self):
    """Whether this test's state is incomplete.

    Returns: bool
    """
    pass

  @abstractmethod
  def get_autotest_results(self):
    """Retrieves the autotest results in the form of (id, result).

    Returns: Iterable[(str, Result.Autotest)]
    """
    pass

  @abstractmethod
  def serialize(self):
    """Returns a serialized representation of the result data.

    Returns: str
    """
    pass

  @abstractmethod
  def add_prejob_response(self, response):
    """Adds a prejob response to this result (overwrites existing).

    Args:
    * response (DUTPrejobResponse): response to a prejob to add to this
    overall response.
    """
    pass

  @abstractmethod
  def add_test_response(self, response):
    """Adds a test response to this result (adds to list).

    Args:
    * response (DUTTestResponse): response to a test to add to this overall
    response.
    """
    pass

  @abstractmethod
  def add_result(self, test_id, result):
    """Adds a result to this response (updates all values accordingly).

    Args:
    * result (DUTResult): Overall result to add to overall response.
    """
    pass

  @abstractmethod
  def get_dut_state(self):
    """Retrieves the state of this dut.

    Returns: str
    """
    pass

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
