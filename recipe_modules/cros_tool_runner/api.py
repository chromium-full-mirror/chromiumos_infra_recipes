# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for cros_tool_runner interface."""

from google.protobuf import json_format

from PB.chromiumos.test.api import cros_tool_runner_cli as ctr
from recipe_engine import recipe_api


class CrosToolRunnerCommand(recipe_api.RecipeApi):
  """Module for issuing CrosToolRunner commands"""

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
    self._docker_key_file_location = '/creds/service_accounts/skylab-drone.json'
    # last created image file path.
    self._images_file_path = None
    # container metadata for last created image file.
    self.container_metadata = None
    # Temporary hack: make it public for minimum code change.
    # TODO(b/250615010): clean up
    self.bot_id = env_vars.SWARMING_BOT_ID

  def create_file_with_container_metadata(self, container_metadata):
    """Create a temp file with provided container metadata.

        Args:
          container_metadata: (ContainerMetadata) container metadata.
        """
    # CTR module allows creating image file from container metadata repeatedly.
    # Every time a new image file is created, previous image file path
    # and container metadata will be replaced by the new one.
    if container_metadata and (self.container_metadata != container_metadata or
                               not self._images_file_path):
      self.container_metadata = container_metadata
      container_metadata_output = json_format.MessageToJson(
          self.container_metadata)
      self._images_file_path = self.m.path.mkstemp(prefix='container_images')
      self.m.file.write_text('writing container metadata to file',
                             self._images_file_path, container_metadata_output)

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
      presentation.logs['request'] = json_format.MessageToJson(request)
      self.ensure_cros_tool_runner()
      preserve_env = [
          # Container cache service info.
          'CONTAINER_CACHE_SERVICE_PORT',
          'CONTAINER_CACHE_SERVICE_HOST',

          # Docker drone info.
          'DRONE_AGENT_HIVE',
          'DOCKER_DRONE_IMAGE',
          'DOCKER_DRONE_SERVER_NAME',

          # Resource limits for docker.
          'DRONE_AGENT_BOT_BLKIO_READ_BPS',
          'DRONE_AGENT_BOT_BLKIO_WRITE_BPS',

          # BBID
          'LOGDOG_STREAM_PREFIX',
          'SWARMING_TASK_ID',

          # Cloudbot Envvars
          'CLOUDBOTS_CA_CERTIFICATE',
          'CLOUDBOTS_LAB_DOMAIN',
          'CLOUDBOTS_PROXY_ADDRESS',
          'SWARMING_BOT_ID',
      ]
      cmd = [
          'sudo',
          '--non-interactive',
          '--preserve-env={}'.format(','.join(preserve_env)),
          self._cmd,
          subcommand,
          '-docker_key_file',
          self._docker_key_file_location,
          '-images',
          self._images_file_path,
          '-input',
          '/dev/stdin',
      ]
      stdin = self.m.raw_io.input_text(json_format.MessageToJson(request))
      if not send_response:  # pragma: nocover
        self.m.easy.step(subcommand, cmd, stdin=stdin)
        return None
      cmd += [
          '-output',
          '/dev/stdout',
      ]
      response = self.m.easy.stdout_jsonpb_step(subcommand, cmd, response_type,
                                                stdin=stdin,
                                                test_output=response_type(),
                                                ok_ret=(0,))
      presentation.logs['response'] = json_format.MessageToJson(response)
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

  def pre_process(self, request):
    """Pre process commands via `pre-process` subcommand.

        Args:
          request: a CrosToolRunnerPreTestRequest.
        """
    return self._run('pre-process', request, ctr.CrosToolRunnerPreTestRequest,
                     ctr.CrosToolRunnerPreTestResponse, send_response=True)

  def test(self, request):
    """Run test(s) via `test` subcommand.

        Args:
          request: a CrosToolRunnerTestRequest.
        """
    return self._run('test', request, ctr.CrosToolRunnerTestRequest,
                     ctr.CrosToolRunnerTestResponse, send_response=True)

  def post_process(self, request):
    """Run post process via `post_process` subcommand.

        Args:
          request: a CrosToolRunnerPostTestRequest.
        """
    return self._run('post-process', request, ctr.CrosToolRunnerPostTestRequest,
                     ctr.CrosToolRunnerPostTestResponse,
                     send_response=True)  # pragma: no cover

  def upload_to_tko(self, autotest_dir, results_dir):
    """Upload test results to TKO via tko-parse.
    This command does not call into CTR. It directly invokes tko-parse in autotest.
    To have parity with phosphorus package, it makes sense to have the implementation live here
    so that any recipe consuming this module can take the benefit of this.

    Args:
      autotest_dir (str): path to autotest package.
      results_dir (str): path to test results to upload.
    """
    with self.m.step.nest('upload-to-tko') as presentation:
      if not autotest_dir:
        raise ValueError('autotest_dir argument is required')
      if not results_dir:
        raise ValueError('results_dir argument is required')
      # A swarming task may have multiple attempts ("runs").
      # The swarming task ID always ends in "0", e.g. "123456789abcdef0".
      # The corresponding runs will have IDs ending in "1", "2", etc., e.g. "123456789abcdef1".
      # All attempts should be recorded under same job ending with 0.
      # This also maintains parity with non-CTR(phosphorus) runs.
      job_name = 'swarming-{}0'.format(self._run_id[:len(self._run_id) - 1])
      tko_parse_path = self.m.path.join(autotest_dir, 'tko', 'parse')
      cmd = self._tko_parse_cmd(tko_parse_path, results_dir, job_name)
      step_stdout = self.m.easy.stdout_step('tko-parse', cmd)
      presentation.logs['tko-parse stdout'] = step_stdout

  def _tko_parse_cmd(self, tko_parse_path, results_dir, job_name):
    """Construct tko-parse command with all necessary args.

    Args:
      tko_parse_path (str): path to tko-parse cli.
      results_dir (str): path to test results to upload.
      job_name (str): job name to be passed to tko-parse.
    """
    args = [tko_parse_path]
    args.append('--write-pidfile')
    args.append(results_dir)
    args.append('--effective_job_name')
    args.append(job_name)
    args.append('-l')
    args.append('3')
    args.append('--record-duration')
    args.append('-r')
    args.append('-o')
    args.append('--suite-report')
    return args

  def ensure_cros_tool_runner(self):
    """Ensure the CrosToolRunner CLI is installed."""
    if self._cmd:
      return

    if not self._version:  # pragma: no cover
      raise ValueError('No version label provided for '
                       'cros_tool_runner CIPD package.')
    if not self._images_file_path:
      if self.container_metadata:
        self.create_file_with_container_metadata(self.container_metadata)
      else:
        raise ValueError('No container metadata provided for '
                         'cros_tool_runner CIPD package.')

    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure cros-tool-runner'):
        cipd_dir = self.m.path.start_dir.join('cipd', 'cros-tool-runner')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/cros-tool-runner/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._cmd = cipd_dir.join('cros-tool-runner')

  def _dut_hostname_from_bot_id(self, swarming_bot_id):
    """Extract the DUT hostname from the env vars.

    Args:
      * env_vars: CrosToolRunnerEnvProperties instance.
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
