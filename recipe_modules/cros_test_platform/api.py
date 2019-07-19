# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.test_platform.steps.enumeration import \
  EnumerationRequest, EnumerationResponse
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequest, SchedulerTrafficSplitResponse
from PB.test_platform.steps.execution import ExecuteRequest, ExecuteResponse


class CrosTestPlatformCommand(recipe_api.RecipeApi):
  """Module for issuing cros_test_platform commands"""

  def initialize(self):
    self._cmd = None
    self._version = 'latest'

  def _run(self, subcommand, request, request_type, response_type):
    """Generic subcommand runner for cros_test_platform.

    All cros_test_platform subcommands take the same basic commandline
    arguments.

    Args:
      subcommand: (str) subcommand to run.
      request: proto input request to subcommand.
      request_type: request must be of this type.
      response_type: response type proto.

    Returns:
      Response, of type response_type.
    """
    with self.m.step.nest('call binary'):
      if not isinstance(request, request_type):
        raise ValueError('request is not of type %s' % request_type)
      self._ensure_cros_test_platform()
      cmd = [
        self._cmd,
        subcommand,
        # TODO(akeshet): recipes_engine/json module, write JSON to/from
        # tempfile rather than stdin/stdout.
        '-input_json',
        '/dev/stdin',
        '-output_json',
        '/dev/stdout',
      ]
      output_json = self.m.easy.stdout_step(
          subcommand,
          cmd,
          stdin=self.m.raw_io.input_text(json_format.MessageToJson(request)),
          test_stdout="{}")
      resp = response_type()
      json_format.Parse(output_json, resp)
      return resp

  def enumerate(self, request):
    """Enumerate test cases via `enumerate` subcommand.

    Args:
      request: a EnumerationRequest.

    Returns: EnumerationResponse.
    """
    return self._run('enumerate', request,
        EnumerationRequest, EnumerationResponse)

  def scheduler_traffic_split(self, request):
    """Determine scheduler via `scheduler-traffic-split` subcommand.

    Args:
      request: a SchedulerTrafficSplitRequest.

    Returns: SchedulerTrafficSplitResponse.
    """
    return self._run('scheduler-traffic-split', request,
        SchedulerTrafficSplitRequest, SchedulerTrafficSplitResponse)

  def skylab_execute(self, request):
    """Execute work via `skylab-execute` subcommand.

    Args:
      request: a ExecuteRequest.

    Returns: ExecuteResponse.
    """
    return self._run('skylab-execute', request,
        ExecuteRequest, ExecuteResponse)

  def autotest_execute(self, request):
    """Execute work via `autotest-execute` subcommand.

    Args:
      request: a ExecuteRequest.

    Returns: ExecuteResponse.
    """
    return self._run('autotest-execute', request,
        ExecuteRequest, ExecuteResponse)

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
