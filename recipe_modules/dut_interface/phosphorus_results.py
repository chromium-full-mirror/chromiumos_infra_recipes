# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Phosphorus Result objects for phosphorus_interface."""

import base64
import zlib

from RECIPE_MODULES.chromeos.dut_interface import dut_results

from PB.test_platform import phosphorus
from PB.test_platform.skylab_test_runner.result import Result


class PhosphorusPrejobDUTResponse(dut_results.DUTPrejobResponse
                                 ):  # pragma: no cover

  def is_failure(self):
    return (self.data and
            self.data.state != phosphorus.prejob.PrejobResponse.SUCCEEDED)

  @staticmethod
  def build_aborted_response(test_id):
    return PhosphorusPrejobDUTResponse(
        test_id=test_id, data=phosphorus.prejob.PrejobResponse(
            state=phosphorus.prejob.PrejobResponse.ABORTED))

  def get_state_name(self):
    return phosphorus.prejob.PrejobResponse.State.Name(self.data.state)


class PhosphorusTestDUTResponse(dut_results.DUTTestResponse
                               ):  # pragma: no cover

  def is_failure(self):
    return (self.data and
            self.data.state != phosphorus.runtest.RunTestResponse.SUCCEEDED)

  def is_skipped(self):
    raise NotImplementedError

  @staticmethod
  def build_aborted_response(test_id):
    return PhosphorusTestDUTResponse(
        test_id=test_id, data=phosphorus.runtest.RunTestResponse(
            state=phosphorus.runtest.RunTestResponse.ABORTED))

  def get_state_name(self):
    return phosphorus.runtest.RunTestResponse.State.Name(self.data.state)


class PhosphorusFetchCrashDUTResponse(dut_results.DUTFetchCrashResponse
                                     ):  # pragma: no cover
  pass


class PhosphorusResult(dut_results.DUTResult):  # pragma: no cover

  def __init__(self, data=None):  # pylint: disable=useless-super-delegation
    """Phosphorus metatada container for all test responses.

    Stores within:
    * skylab_test_runner.result.Result
    * dut_results.DUTTestResponse
    * dut_results.DUTPrejobResponse

    Args:
    * data (skylab_test_runner.result.Result): Phosphorus metadata for a
    result response.
    """
    super().__init__(data)

  def is_failure(self):
    verdicts = [
        p.verdict != Result.Prejob.Step.VERDICT_PASS
        for p in self.data.prejob.step
    ]

    incomplete = []

    for test_result in self.data.autotest_results.values():
      if test_result.incomplete:
        incomplete.append(test_result)
      for t in test_result.test_cases:
        if t.verdict != Result.Autotest.TestCase.VERDICT_PASS:
          verdicts.append(t)

    return any(verdicts) or self.data.autotest_result.incomplete or any(
        incomplete)

  def update_log_urls(self, metadata):
    # Logs are archived even in the case of catastrophic failures.
    # Thus, it is possible that we do not have a good result message.
    self.data.log_data.gs_url = metadata.gs_url
    self.data.log_data.testhaus_url = metadata.testhaus_logs_url

  def get_testhaus_log_url(self):
    return self.data.log_data.testhaus_url

  def get_prejob_steps(self):
    return self.data.prejob.step

  def is_test_incomplete(self):
    return self.data.autotest_result.incomplete

  def get_test_results(self):
    return self.data.autotest_results.items()

  def get_dut_state(self):
    return self.data.state_update.dut_state

  def serialize(self):
    return base64.b64encode(zlib.compress(self.data.SerializeToString()))

  def add_prejob_response(self, response):
    self.prejob_response = response

  def add_test_response(self, response):
    if response:
      self.test_responses.append(response)

  def add_result(self, test_id, result):
    self.data = result.data
    self.prejob_response = result.prejob_response
    if result.data.HasField('autotest_result'):
      self.data.autotest_results[test_id].CopyFrom(result.data.autotest_result)
    for test_response in result.test_responses:
      self.add_test_response(test_response)
