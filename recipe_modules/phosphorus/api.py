# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for issuing Phosphorus commands"""

from google.protobuf import json_format

from PB.test_platform.phosphorus.fetchcrashes import FetchCrashesRequest
from PB.test_platform.phosphorus.fetchcrashes import FetchCrashesResponse
from PB.test_platform.phosphorus.prejob import PrejobRequest
from PB.test_platform.phosphorus.prejob import PrejobResponse
from PB.test_platform.phosphorus.runtest import RunTestRequest
from PB.test_platform.phosphorus.runtest import RunTestResponse
from PB.test_platform.phosphorus.upload_to_gs import UploadToGSRequest
from PB.test_platform.phosphorus.upload_to_gs import UploadToGSResponse
from PB.test_platform.phosphorus.upload_to_tko import UploadToTkoRequest
from PB.test_platform.skylab_local_state.load import LoadRequest
from PB.test_platform.skylab_local_state.load import LoadResponse
from PB.test_platform.skylab_local_state.remove import RemoveRequest
from PB.test_platform.skylab_local_state.save import SaveRequest
from PB.test_platform.skylab_test_runner.result import Result
from PB.uprev.build_parallels_image.common import Config as ParallelsConfig
from PB.uprev.build_parallels_image.provision import ProvisionRequest as \
  ParallelsProvisionRequest
from PB.uprev.build_parallels_image.save import SaveRequest as \
  ParallelsSaveRequest
from recipe_engine import recipe_api


class PhosphorusCommand(recipe_api.RecipeApi):

  def __init__(self, properties, env_vars, **kwargs):
    super().__init__(**kwargs)
    self._cmd = None
    self._version = str(properties.version.cipd_label)
    self._config = properties.config
    # dut_hostname represents schedulable unit from inventory(e.g. UFS),
    # which can be hostname of a DUT itself(single DUT use case), or
    # name of a scheduling unit(multi-DUTs use case).
    if env_vars.SWARMING_BOT_ID.startswith('cloudbots-'):
      self._dut_hostname = env_vars.CLOUDBOTS_DUT_HOSTNAME
    else:
      self._dut_hostname = self._dut_hostname_from_bot_id(
          env_vars.SWARMING_BOT_ID)
    self._dut_id = env_vars.SKYLAB_DUT_ID
    self._run_id = env_vars.SWARMING_TASK_ID
    self._local_state_results_dir = ''

  def _run(self, subcommand, request, request_type, response_type=None,
           send_response=False):
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
      presentation.logs['request'] = json_format.MessageToJson(request)
      self._ensure_phosphorus()
      cmd = [
          self._cmd,
          subcommand,
          '-input_json',
          '/dev/stdin',
      ]
      stdin = self.m.raw_io.input_text(json_format.MessageToJson(request))
      if not send_response:
        self.m.easy.step(subcommand, cmd, stdin=stdin)
        return None
      cmd += [
          '-output_json',
          '/dev/stdout',
      ]
      response = self.m.easy.stdout_jsonpb_step(subcommand, cmd, response_type,
                                                stdin=stdin,
                                                test_output=response_type(),
                                                parse_before_str=b'\x00',
                                                ok_ret=(0,))
      presentation.logs['response'] = json_format.MessageToJson(response)
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

  def fetch_crashes(self, request):
    """Fetch crashes via the `fetch-crashes` subcommand.

    Args:
      request: a FetchCrashesRequest.
    """
    return self._run('fetch-crashes', request, FetchCrashesRequest,
                     FetchCrashesResponse, send_response=True)

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

  def parse(self, results_dir):
    """Extract test results from an results directory.

    Args:
      results_dir: a string pointing to a directory containing test results.

    Returns: Result.
    """
    with self.m.step.nest('call `phosphorus`') as presentation:
      if not results_dir:
        raise ValueError('No results directory provided')
      self._ensure_phosphorus()
      cmd = [
          self._cmd,
          'parse',
          results_dir,
      ]
      result = self.m.easy.stdout_jsonpb_step('parse', cmd, Result,
                                              test_output=Result())
      presentation.logs['response'] = json_format.MessageToJson(result)
      return result

  def _ensure_phosphorus(self):
    """Ensure the phosphorus CLI is installed."""
    if self._cmd:
      return
    if not self._version:  # pragma: no cover
      raise ValueError('No version label provided for '
                       'phosphorus CIPD package.')

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure phosphorus'):
        cipd_dir = self.m.path.start_dir.join('cipd', 'phosphorus')
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

  def save_skylab_local_state(self, dut_state, dut_name, peer_duts,
                              repair_requests=None):
    """Update the local DUT state file.

    Args:
      * dut_state: DUT state string (e.g. 'ready').
      * dut_name: Hostname of the primary DUT.
      * peer_duts: A list of hostnames for peer DUTs.
      * repair_requests (array): Requests to enforce repair actions.

    Raises:
      * InfraFailure
    """
    return self._save_skylab_local_state(dut_state, dut_name,
                                         peer_duts=peer_duts,
                                         seal_results_dir=False,
                                         repair_requests=repair_requests)

  def save_and_seal_skylab_local_state(self, dut_state, dut_name, peer_duts,
                                       repair_requests=None):
    """Update the local DUT state file and seal the results directory.

    Args:
      * dut_state: DUT state string (e.g. 'ready').
      * dut_name: Hostname of the primary DUT.
      * peer_duts: A list of hostnames for peer DUTs.
      * repair_requests (array): Requests to enforce repair actions.

    Raises:
      * InfraFailure
    """
    return self._save_skylab_local_state(dut_state, dut_name,
                                         peer_duts=peer_duts,
                                         seal_results_dir=True,
                                         repair_requests=repair_requests)

  def _save_skylab_local_state(self, dut_state, dut_name, peer_duts,
                               seal_results_dir, repair_requests=None):
    """Update the local DUT state, and repair-requests, and seal results dir.

    Args:
      * dut_state (str): DUT state string (e.g. 'ready').
      * dut_name (str): Hostname of the primary DUT.
      * peer_duts (array): A list of hostnames for peer DUTs.
      * seal_results_dir (bool): Specify if result directory need to be sealed.
      * repair_requests (array): Requests to enforce repair actions.

    Raises:
      * ValueError
    """
    if repair_requests is None:
      repair_requests = []
    with self.m.context(infra_steps=True):
      if not self._local_state_results_dir:
        raise ValueError(
            'Results directory not set. Did you call load() first?')
      request = SaveRequest(config=self._config, dut_name=dut_name,
                            dut_id=self._dut_id, dut_state=dut_state,
                            results_dir=self._local_state_results_dir,
                            seal_results_dir=seal_results_dir,
                            peer_duts=peer_duts,
                            repair_requests=repair_requests)
      self._run('save', request, SaveRequest)

  def remove_autotest_results_dir(self):
    """Remove the autotest results directory.

    Raises:
      * InfraFailure
    """
    with self.m.context(infra_steps=True):
      request = RemoveRequest(config=self._config, run_id=self._run_id)
      self._run('remove', request, RemoveRequest)

  def build_parallels_image_provision(self, image_gs_path,
                                      max_duration_sec=2 * 60 * 60):
    """Provisions a DUT with the given CrOS image and Parallels DLC.

    Args:
      image_gs_path (str): The Google Storage path (prefix) where images are
        located. For example,
        'gs://chromeos-image-archive/eve-release/R86-13380.0.0'.
      max_duration_sec (int): Maximum duration of the provision operation, in
        seconds. Defaults to two hours.
    """
    with self.m.context(infra_steps=True):
      request = ParallelsProvisionRequest(
          config=self._build_parallels_image_config(),
          dut_name=self._dut_hostname, image_gs_path=image_gs_path)

      request.deadline.seconds = int(self.m.time.ms_since_epoch() / 1000 +
                                     max_duration_sec)

      self._run('build-parallels-image-provision', request,
                ParallelsProvisionRequest)

  def build_parallels_image_save(self, dut_state):
    """Saves the given DUT state in UFS.

    The state is only saved if it is safe to do so (i.e. is currently ready
    or needs_repair).

    Args:
      dut_state (str): The new DUT state. E.g. "needs_repair" or "ready".
    """
    with self.m.context(infra_steps=True):
      request = ParallelsSaveRequest(
          config=self._build_parallels_image_config(),
          dut_name=self._dut_hostname, dut_state=dut_state)
      self._run('build-parallels-image-save', request, ParallelsSaveRequest)

  def _build_parallels_image_config(self):
    return ParallelsConfig(cros_ufs_service=self._config.cros_ufs_service)

  def _dut_hostname_from_bot_id(self, swarming_bot_id):
    """Extract the DUT hostname from the env vars.

    Args:
      * env_vars: PhosphorusEnvProperties instance.
    """
    expected_prefixes = self._read_bot_prefix()
    for expected_prefix in expected_prefixes:
      if swarming_bot_id.startswith(expected_prefix):
        return swarming_bot_id[len(expected_prefix):]
    return swarming_bot_id

  def read_dut_hostname(self):
    """"Return the DUT hostname."""
    return self._dut_hostname

  def _read_bot_prefix(self):
    """Extract the bot prefix from the config properties."""
    if self._config and self._config.bot_prefix:
      return [str(self._config.bot_prefix)]
    return ['crossk-', 'cros-']
