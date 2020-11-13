# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.test_platform.skylab_local_state.load import LoadRequest, LoadResponse
from PB.test_platform.skylab_local_state.save import SaveRequest
from PB.test_platform.phosphorus.prejob import PrejobRequest, PrejobResponse
from PB.test_platform.phosphorus.runtest import RunTestRequest, RunTestResponse
from PB.test_platform.phosphorus.upload_to_tko import UploadToTkoRequest
from PB.test_platform.phosphorus.upload_to_gs import UploadToGSRequest
from PB.test_platform.phosphorus.upload_to_gs import UploadToGSResponse

class PhosphorusCommand(recipe_api.RecipeApi):
  """Module for issuing Phosphorus commands"""

  def __init__(self, properties, env_vars, **kwargs):
    super(PhosphorusCommand, self).__init__(**kwargs)
    self._cmd = None
    self._version = str(properties.version.cipd_label)
    self._config = properties.config
    self._dut_hostname = self._dut_hostname_from_bot_id(
        env_vars.SWARMING_BOT_ID)
    self._dut_id = env_vars.SKYLAB_DUT_ID
    self._run_id = env_vars.SWARMING_TASK_ID
    self._local_state_results_dir = ''
    if not self._version: # pragma: no cover
      raise ValueError('No version label provided for '
          'phosphorus CIPD package.')

  def _run(self,
           subcommand,
           request, request_type,
           response_type=None, send_response=False):
    """Generic subcommand runner for phosphorus.

    Args:
      subcommand: (str) subcommand to run
      request: proto input request to subcommand
      request_type: request must be of this type.
      response_type: response will be interpreted as this type.
      send_response: whether to relay a response from the command to the caller
    Returns:
      JSON proto of response_type if send_response is set, None otherwise
    """
    with self.m.step.nest('call `phosphorus`') as presentation:
      if not isinstance(request, request_type):
        raise ValueError('request is not of type %s' % request_type)
      presentation.logs['request'] = [json_format.MessageToJson(request)]
      self._ensure_phosphorus()
      cmd = [
        self._cmd,
        subcommand,
        '-input_json',
        '/dev/stdin',
      ]
      stdin=self.m.raw_io.input_text(json_format.MessageToJson(request))
      if not send_response:
        self.m.easy.step(subcommand, cmd, stdin=stdin)
        return
      cmd += [
          '-output_json',
          '/dev/stdout',
      ]
      response = self.m.easy.stdout_jsonpb_step(
          subcommand,
          cmd,
          response_type,
          stdin=stdin,
          test_output=response_type(),
          ok_ret=(0,))
      presentation.logs['response'] = [json_format.MessageToJson(response)]
      return response

  def prejob(self, request):
    """Run a prejob or a provision via `prejob` subcommand.

    Args:
      request: a PrejobRequest.
    """
    return self._run('prejob', request, PrejobRequest, PrejobResponse,
                     send_response=True)

  def run_test(self, request):
    """Run a test via `run-test` subcommand.

    Args:
      request: a RunTestRequest.
    """
    return self._run('run-test', request, RunTestRequest, RunTestResponse,
                     send_response=True)

  def upload_to_gs(self, request):
    """Upload selected test results to GS via `upload-to-gs` subcommand.

    Args:
      request: an UploadToGSRequest.
    """
    return self._run('upload-to-gs', request, UploadToGSRequest,
              UploadToGSResponse, send_response=True)

  def upload_to_tko(self, request):
    """Upload test results to TKO via `upload-to-tko` subcommand.

    Args:
      request: an UploadToTkoRequest.
    """
    self._run('upload-to-tko', request, UploadToTkoRequest)

  def _ensure_phosphorus(self):
    """Ensure the phosphorus CLI is installed."""
    if self._cmd:
      return

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure phosphorus'):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'phosphorus')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/phosphorus/${platform}',
                          self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._cmd = cipd_dir.join('phosphorus')

  def load_skylab_local_state(self, test_id):
    """Load the local DUT state file.

    Raises:
      * InfraFailure
    """
    with self.m.context(infra_steps=True):
      request = LoadRequest(config=self._config, dut_name=self._dut_hostname,
                            run_id=self._run_id, dut_id=self._dut_id,
                            test_id=test_id)
      result = self._run('load', request, LoadRequest, LoadResponse,
                         send_response=True)
      self._local_state_results_dir = result.results_dir
      return result

  def save_skylab_local_state(self, dut_state):
    """Update the local DUT state file.

    Args:
      * dut_state: DUT state string (e.g. 'ready').

    Raises:
      * InfraFailure
    """
    return self._save_skylab_local_state(dut_state, False)

  def save_and_seal_skylab_local_state(self, dut_state):
    """Update the local DUT state file and seal the results directory.

    Args:
      * dut_state: DUT state string (e.g. 'ready').

    Raises:
      * InfraFailure
    """
    return self._save_skylab_local_state(dut_state, True)

  def _save_skylab_local_state(self, dut_state, seal_results_dir):
    with self.m.context(infra_steps=True):
      if not self._local_state_results_dir:
        raise ValueError(
            'Results directory not set. Did you call load() first?')

      request = SaveRequest(config=self._config, dut_name=self._dut_hostname,
                            dut_id=self._dut_id, dut_state=dut_state,
                            results_dir=self._local_state_results_dir,
                            seal_results_dir=seal_results_dir)
      self._run('save', request, SaveRequest)

  def _dut_hostname_from_bot_id(self, swarming_bot_id):
    """Extract the DUT hostname from the env vars.

    Args:
      * env_vars: PhosphorusEnvProperties instance.

    Raises:
      * AssertionError if the Swarming bot ID env var is missing or invalid.
    """
    expected_prefix = 'crossk-'
    assert swarming_bot_id.startswith(expected_prefix)
    return swarming_bot_id[len(expected_prefix):]

  def read_dut_hostname(self):
    """"Return the DUT hostname."""
    return self._dut_hostname
