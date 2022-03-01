# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api
from PB.chromiumos.test.api import cros_tool_runner_cli as ctr


class CrosToolRunnerCommand(recipe_api.RecipeApi):
  """Module for issuing CrosToolRunner commands"""

  def __init__(self, properties, env_vars, **kwargs):
    super(CrosToolRunnerCommand, self).__init__(**kwargs)
    self._cmd = None
    self._version = str(properties.version.cipd_label)
    self.container_metadata = properties.container_metadata
    # dut_hostname represents schedulable unit from inventory(e.g. UFS),
    # which can be hostname of a DUT itself(single DUT use case), or
    # name of a scheduling unit(multi-DUTs use case).
    self._dut_hostname = self._dut_hostname_from_bot_id(
        env_vars.SWARMING_BOT_ID)
    self._dut_id = env_vars.SKYLAB_DUT_ID
    self._run_id = env_vars.SWARMING_TASK_ID
    self._docker_key_file_location = '/creds/service_accounts/skylab-drone.json'

  def _run(self, subcommand, request, request_type, response_type=None,
           send_response=False):
    """Generic subcommand runner for cros_tool_runner.

        Args:
          subcommand: (str) subcommand to run.
          request: proto input request to subcommand.
          request_type: request must be of this type.
          response_type: response will be interpreted as this type.
          send_response: whether to relay a response from the command to the caller
        Returns:
          JSON proto of response_type if send_response is set, None otherwise
        """
    with self.m.step.nest('call `cros-tool-runner`') as presentation:
      if not isinstance(request, request_type):
        raise ValueError('request is not of type %s' % request_type)
      presentation.logs['request'] = [json_format.MessageToJson(request)]
      self._ensure_cros_tool_runner()
      fileName = "images.json"
      with open(fileName, 'w') as f:
        f.write(json_format.MessageToJson(self.container_metadata))
      cmd = [
          "sudo",
          "--non-interactive",
          self._cmd,
          subcommand,
          '-docker_key_file',
          self._docker_key_file_location,
          '-images',
          fileName,
          '-input',
          '/dev/stdin',
      ]
      stdin = self.m.raw_io.input_text(json_format.MessageToJson(request))
      if not send_response:  # pragma: nocover
        self.m.easy.step(subcommand, cmd, stdin=stdin)
        return
      cmd += [
          '-output',
          '/dev/stdout',
      ]
      response = self.m.easy.stdout_jsonpb_step(subcommand, cmd, response_type,
                                                stdin=stdin,
                                                test_output=response_type(),
                                                ok_ret=(0,))
      presentation.logs['response'] = [json_format.MessageToJson(response)]
      return response

  def provision(self, request):
    """Run provision via `provision` subcommand.

        Args:
          request: a CrosToolRunnerProvisionRequest.
        """
    return self._run('provision', request, ctr.CrosToolRunnerProvisionRequest,
                     ctr.CrosToolRunnerProvisionResponse, send_response=True)

  def find_tests(self, request):
    """Find tests via `test-finder` subcommand.

        Args:
          request: a CrosToolRunnerTestFinderRequest.
        """
    return self._run('test-finder', request,
                     ctr.CrosToolRunnerTestFinderRequest,
                     ctr.CrosToolRunnerTestFinderResponse, send_response=True)

  def test(self, request):
    """Run test(s) via `test` subcommand.

        Args:
          request: a CrosToolRunnerTestRequest.
        """
    return self._run('test', request, ctr.CrosToolRunnerTestRequest,
                     ctr.CrosToolRunnerTestResponse, send_response=True)

  def _ensure_cros_tool_runner(self):
    """Ensure the CrosToolRunner CLI is installed."""
    if self._cmd:
      return

    if not self._version:  # pragma: no cover
      raise ValueError('No version label provided for '
                       'cros_tool_runner CIPD package.')

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure cros-tool-runner'):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'cros-tool-runner')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/cros-tool-runner/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._cmd = cipd_dir.join('cros-tool-runner')

  def _dut_hostname_from_bot_id(self, swarming_bot_id):
    """Extract the DUT hostname from the env vars.

        Args:
          * env_vars: CrosToolRunnerEnvProperties instance.

        Raises:
          * AssertionError if the Swarming bot ID env var is missing or invalid.
        """
    expected_prefix = 'crossk-'
    assert swarming_bot_id.startswith(expected_prefix)
    return swarming_bot_id[len(expected_prefix):]

  def read_dut_hostname(self):
    """"Return the DUT hostname."""
    return self._dut_hostname
