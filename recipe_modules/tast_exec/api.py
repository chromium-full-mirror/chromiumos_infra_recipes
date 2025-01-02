# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
import os
from recipe_engine.recipe_api import RecipeApi

class TastExecApi(RecipeApi):
  """A module to execute tast commands."""

  class TastInputs():
    """Common inputs for TastExecApi methods.

    Args:
      expressions (list[str]): Expressions describing tests to run.
      test_artifacts_dir (Path): Dir containing test artifacts.
      build_payload (BuildPayload): Where the build artifact is on GS.
      run_args (list[str]): Additional arguments to pass to the `tast run`
          command (optional).
      shard_args (list[str]): Arguments that indicate how the test should be
          sharded (optional). Note that this is split from run_args since these
          args need to be passed to both `tast run` and `tast list`.
    """

    def __init__(self, expressions, test_artifacts_dir, build_payload,
                 run_args=None, shard_args=None):
      self.expressions = expressions
      self.test_artifacts_dir = test_artifacts_dir
      self.build_payload = build_payload
      self.run_args = run_args or []
      self.shard_args = shard_args or []

    def copy(self):
      """Make a new TastInputs with the same field values."""
      return copy.deepcopy(self)

    def build_artifacts_url(self):
      """GS URL where the build artifacts are located."""
      return 'gs://{}/{}/'.format(self.build_payload.artifacts_gs_bucket,
                                  self.build_payload.artifacts_gs_path)

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._exec_timeout = properties.exec_timeout or 90 * 60
    self._vm_system_services_timeout = properties.vm_system_services_timeout or 10 * 60
    self._public_builder = properties.public_builder
    self._tast_cli_supported_flags = []

  def download_tast(self, build_payload, test_artifacts_dir):
    """Downloads the tast executable from specified build artifacts.

    Args:
      build_payload (BuildPayload): Describes where the artifact is on GS.
      test_artifacts_dir (str): The directory to which files should be
        downloaded. The tast executable will be found at tast/tast relative
        to this directory.
    """
    with self.m.step.nest('setup tast') as presentation:
      presentation.text = 'download tast executable'
      sp_tar_file = test_artifacts_dir / 'autotest_server_package.tar.bz2'
      archive_path = os.path.join(build_payload.artifacts_gs_path,
                                  'autotest_server_package.tar.bz2')
      self.m.gsutil.download(build_payload.artifacts_gs_bucket, archive_path,
                             sp_tar_file, name='download tast bundle from GS')
      self.m.step(
          'untar tast',
          ['tar', 'xjf', sp_tar_file, '--directory', test_artifacts_dir])

  def _amend_tast_inputs(self, tast_inputs: TastInputs) -> TastInputs:
    """Modifies TastInputs based on the given Tast version.

    Ensures that newer flags are not passed in when running Tast on images
    created using an older source.

    Currently checks for the existance of the following flags:
      * systemservicestimeout:
          Not passed in by default, added if it is supported.
      * shardmethod:
          Passed in by default, removed if it is not supported.

    Args:
      TastInputs: Inputs for executing Tast.

    Returns:
      A copy of TastInputs with potentially modified flags.
    """
    tast_inputs = tast_inputs.copy()
    if self._flag_exists(tast_inputs.test_artifacts_dir / 'tast',
                         'systemservicestimeout'):
      tast_inputs.run_args.append('-systemservicestimeout={}'.format(
          self._vm_system_services_timeout))

    # Check if the shardmethod flag exists before passing it in.
    if not self._flag_exists(tast_inputs.test_artifacts_dir / 'tast',
                             'shardmethod'):
      tast_inputs.shard_args = [
          x for x in tast_inputs.shard_args if not x.startswith('-shardmethod')
      ]

    return tast_inputs

  def run_direct(self, dut_name, tast_inputs, test_results_dir):
    """Run tast tests without retries or results processing.

    Args:
      dut_name (str): The identity of the DUT to connect to,
        for example, my-dut-host-name or localhost:9222 (if testing a VM).
      tast_inputs (TastInputs): Common inputs for running tast tests.
      test_results_dir (Path): Path to store tast results.

    Returns:
      list[str]: The list of tests that met the specified expression(s).
    """
    # Used by tast to determine where to download private bundles.
    tast_inputs = tast_inputs.copy()
    tast_inputs.test_artifacts_dir = tast_inputs.test_artifacts_dir / 'tast'
    tests = self._list_tests(dut_name, tast_inputs)
    if tests:
      self._run_tests(dut_name, tast_inputs, test_results_dir)
    return tests

  def _list_tests(self, dut_name, tast_inputs):
    tast_dir = tast_inputs.test_artifacts_dir
    private_builder = 'false' if self._public_builder else 'true'
    private_bundles_str = '-downloadprivatebundles={}'.format(private_builder)

    list_stdout = self.m.easy.stdout_step('tast list', [
        str(tast_dir / 'tast'), \
        'list', \
        '-build=false', \
        private_bundles_str, \
        '-buildartifactsurl={}'.format(tast_inputs.build_artifacts_url()), \
        '-remotebundledir={}'.format(
            str(tast_dir.joinpath('bundles').joinpath('remote'))), \
        '-remotedatadir={}'.format(str(
            tast_dir / 'data')), \
        '-remoterunner={}'.format(
            str(tast_dir / 'remote_test_runner'))] + \
    tast_inputs.shard_args + \
    [dut_name] + \
    list(tast_inputs.expressions), timeout=5 * 60,
    test_stdout=self._test_data.get('simulate_test_list_ret')).decode('utf-8')

    tests = [t.strip() for t in list_stdout.splitlines()]
    return tests

  def _flag_exists(self, tast_dir, flag_name):
    if not self._tast_cli_supported_flags:
      tast_help_stdout = self.m.easy.stdout_step('tast help run', [
          str(tast_dir / 'tast'), \
          'help', \
          'run'], test_stdout='-shardmethod\n-systemservicestimeout').decode('utf-8')
      self._tast_cli_supported_flags = [
          t.strip().split(' ')[0]
          for t in tast_help_stdout.splitlines()
          if t.strip().startswith('-')
      ]
    # append '-' in the beginning if do not exist
    if not flag_name.startswith('-'):
      flag_name = '-{}'.format(flag_name)
    return flag_name in self._tast_cli_supported_flags

  def _run_tests(self, dut_name, tast_inputs, test_results_dir):
    tast_dir = tast_inputs.test_artifacts_dir
    private_builder = 'false' if self._public_builder else 'true'
    private_bundles_str = '-downloadprivatebundles={}'.format(private_builder)
    maybemissingvars_args = []
    if self._public_builder:
      maybemissingvars_args = [r'-maybemissingvars=.+\..+']

    self.m.step('tast run', [
        str(tast_dir / 'tast'), \
        '-verbose', \
        'run', \
        '-build=false', \
        '-sshretries=2', \
        private_bundles_str, \
        '-buildartifactsurl={}'.format(tast_inputs.build_artifacts_url()), \
        '-waituntilready', \
        '-continueafterfailure', \
        '-extrauseflags=tast_vm', \
        '-var=setup.FieldTrialConfig=disable',
        '-defaultvarsdir={}'.format(str(tast_dir / 'vars')), \
        '-resultsdir', str(test_results_dir), \
        '-remotebundledir={}'.format(
            str(tast_dir.joinpath('bundles').joinpath('remote'))), \
        '-remotedatadir={}'.format(str(
            tast_dir / 'data')), \
        '-remoterunner={}'.format(
            str(tast_dir / 'remote_test_runner'))] + \
        maybemissingvars_args + \
        tast_inputs.run_args + \
        tast_inputs.shard_args + \
        [dut_name] + \
        list(tast_inputs.expressions), ok_ret='any', timeout=self._exec_timeout)
