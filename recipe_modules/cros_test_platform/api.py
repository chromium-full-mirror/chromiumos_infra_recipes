# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.test_platform.steps.enumeration import \
  EnumerationRequests, EnumerationResponses
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequests, SchedulerTrafficSplitResponses
from PB.test_platform.steps.execution import ExecuteRequests, ExecuteResponses

# This exit code is returned by cros_test_platform runs that had an error but
# produced a response anyway.
_RETCODE_PARTIAL_RESPONSE = 2


class CrosTestPlatformCommand(recipe_api.RecipeApi):
  """Module for issuing cros_test_platform commands"""

  def initialize(self):
    self._cmd = None
    self._version = 'latest'

  def _run(self, subcommand, request, request_type, response_type,
           tagged=False):
    """Generic subcommand runner for cros_test_platform.

    All cros_test_platform subcommands take the same basic commandline
    arguments.

    Args:
      subcommand: (str) subcommand to run.
      request: proto input request to subcommand.
      request_type: request must be of this type.
      response_type: response type proto.
      tagged: (bool) If True, use tagged requests.

    Returns:
      Response, of type response_type.
    """
    with self.m.step.nest('call binary') as s:
      if not isinstance(request, request_type):
        raise ValueError('request is not of type %s' % request_type)
      self._ensure_cros_test_platform()
      cmd = [
        self._cmd,
        subcommand,
        '-input_json',
        '/dev/stdin',
        '-output_json',
        '/dev/stdout',
      ]
      if tagged:
        cmd.append('-tagged')
      s.presentation.logs['request'] = [json_format.MessageToJson(request)]
      response = self.m.easy.stdout_jsonpb_step(
          subcommand,
          cmd,
          response_type,
          stdin=self.m.raw_io.input_text(json_format.MessageToJson(request)),
          test_output=response_type(),
          # TODO(crbug.com/1008921): Surface non-zero return codes as a step
          # warning.
          ok_ret=(0, _RETCODE_PARTIAL_RESPONSE))
      s.presentation.logs['response'] = [json_format.MessageToJson(response)]
      return response

  def enumerate(self, request):
    """Enumerate test cases via `enumerate` subcommand.

    Args:
      request: a EnumerationRequest.

    Returns: EnumerationResponse.
    """
    return self._run('enumerate', request, EnumerationRequests,
                     EnumerationResponses, tagged=True)

  def scheduler_traffic_split(self, request):
    """Determine scheduler via `scheduler-traffic-split` subcommand.

    Args:
      request: a SchedulerTrafficSplitRequests.

    Returns: SchedulerTrafficSplitResponses.
    """
    return self._run('scheduler-traffic-split', request,
                     SchedulerTrafficSplitRequests,
                     SchedulerTrafficSplitResponses, tagged=True)

  def skylab_execute(self, request):
    """Execute work via `skylab-execute` subcommand.

    Args:
      request: a ExecuteRequest.

    Returns: ExecuteResponse.
    """
    return self._run('skylab-execute', request,
        ExecuteRequests, ExecuteResponses)

  def autotest_execute(self, request):
    """Execute work via `autotest-execute` subcommand.

    Args:
      request: a ExecuteRequest.

    Returns: ExecuteResponse.
    """
    return self._run('autotest-execute', request,
        ExecuteRequests, ExecuteResponses)

  def _ensure_cros_test_platform(self):
    """Ensure the cros_test_platform CLI is installed."""
    if self._cmd:
      return

    with self.m.step.nest('ensure cros_test_platform'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'cros_test_platform')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/cros_test_platform/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cmd = cipd_dir.join('cros_test_platform')
