# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import base64
import os
import re

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2
from PB.test_platform.request import Request

TestExecutionBehavior = Request.Params.TestExecutionBehavior


class ResultDBCommand(recipe_api.RecipeApi):
  """Module for chromium tests on skylab to upload result to Result DB."""

  def __init__(self, **kwargs):
    super(ResultDBCommand, self).__init__(**kwargs)
    self._result_adapter = None

  @property
  def current_invocation_id(self):
    """Return the current invocation's id."""
    inv_id = self.m.resultdb.invocation_ids(
        [self.m.resultdb.current_invocation])
    return str(inv_id[0])

  def extract_resultdb_settings(self, test_args):
    """Extract resultdb settings from test_args.

    Args:
      test_args (str): A string of extra autotest arguments.

    Returns:
      A dictionary wrapping all ResultDB upload parameters.

    Raises:
      ValueError: If resultdb settings are not found in the test_args.
    """
    arg_re = re.compile(r'(\w+)[:=](.*)$')
    args_dict = {}
    for arg in test_args.split():
      match = arg_re.match(arg)
      if match:
        args_dict[match.group(1).lower()] = match.group(2)
    rdb_settings = base64.b64decode(args_dict.get('resultdb_settings', ''))
    if not rdb_settings:
      raise ValueError('test_args should contain resultdb_settings to '
                       'upload result to resultdb. Got %s')
    return self.m.json.loads(rdb_settings)

  def upload_chromium_tests(self, test_args, base_dir):
    """Wrapper for uploading chromium tests to resultDB.

    Chromium tests pass in resultDB parameters via autotest test_args. We must
    extract them before uploading.

    Args:
      test_args (string): Extra autotest arguments, e.g. "key1=val1 key2=val2".
          Chromium tests use test_arg to pass runtime parameters to our autotest
          wrapper. We reuse it to pipe resultDB arguments, because it is easy to
          access in the test runner recipe. test_args must contain
          resultdb_settings which is base64 compressed json string, wrapping all
          resultdb parameters.
      base_dir (string): The path of the base test results on the drone server.
          For example, Chromium gtest result can be found at
          base_dir/autoserv_test/chromium/results.
    """
    with self.m.step.nest('upload chromium test results to rdb'):
      config = self.extract_resultdb_settings(test_args)
      return self._upload(config, base_dir)

  def upload_chromeos_tests(self, base_dir, stainless_url=None):
    """Wrapper for uploading Chrome OS tests to resultDB.

    Currently only supports Tast tests.

    Args:
      base_dir (string): The path of the base test results on the drone server.
      stainless_url (string): Link to the Stainless logs for the test run.
    """
    with self.m.step.nest('upload test results to rdb'):

      base_variant = {}

      # TODO(b/196956525): Pass in desired variant information via config.
      board = self.m.cros_tags.get_values('label-board')
      if board:
        base_variant['board'] = board[0]

      build = self.m.cros_tags.get_values('build')
      if build:
        base_variant['build'] = build[0]

      # TODO(b/200703493): Only Chrome OS Tast tests are currently supported.
      # Calling rdb-stream with other result formats will fail to upload, but
      # not fail the test run.
      config = {
          'result_format': 'tast',
          'base_variant': base_variant,
      }
      return self._upload(config, base_dir, stainless_url)

  def _upload(self, config, base_dir, stainless_url=None):
    """Call the resultDB module to upload test result

    Args:
      config (dict) A dict wrapping all resultdb parameters. The below two are
          handled differently on CrOS:
          * result_file: hardcoded for tast and gtest in this module. It
            should be user invisible.
          * artifact_directory: rel path relative to autotest result folder.
            ONLY for gtest, E.g. chromium/debug. For tast test, we rely on
            it to pass the runtime result path to adapter. So we do
            not accept user defined artifact fed to this module.
          For other supported parameters, refer recipe_engine/resultdb module.
      base_dir - The path of the base test results on the drone server.
          For example, Chromium gtest result can be found at
          base_dir/autoserv_test/chromium/results.
      stainless_url (string): Link to the Stainless logs for the test run.
    """
    assert config.get('result_format') in [
        'gtest', 'json', 'single', 'tast'
    ], ('result_format must be gtest, json, single or tast, '
        'got %s' % config.get('result_format'))
    # Test results on Drone server are not stored in swarming [start_dir],
    # e.g. "/usr/local/autotest/results/swarming-12345678/1".
    # So use general os.path to join.
    base = os.path.join(base_dir, 'autoserv_test')
    result_file_by_type = {
        'gtest': os.path.join(base, 'chromium/results/output.json'),
        'tast': os.path.join(base, 'tast/results/streamed_results.jsonl'),
    }

    # ResultDB in CrOS recipes only supports uploading result file,
    # so the cmd must accompany the result_adapter.
    self._ensure_result_adapter_executables()
    result_adapter = [
        self._result_adapter,
        config.get('result_format'),
        '-result-file',
        result_file_by_type.get(config.get('result_format')),
    ]

    artifact_path = ['-artifact-directory']
    if config.get('result_format') == 'tast':
      artifact_path += [base]
    elif config.get('artifact_directory'):
      artifact_path += [
          os.path.join(base, config.get('artifact_directory', '')),
      ]
    if len(artifact_path) > 1:
      result_adapter.extend(artifact_path)

    # Skylab tests can not wrap directly by rdb now. We only care the
    # result file from the test runs.
    rdb_cmd = result_adapter + ['--'] + ['echo']

    base_tags = [tuple(x.split(':', 1)) for x in config.get('base_tags', [])]

    # wrap it with rdb-stream
    cmd = self.m.resultdb.wrap(
        rdb_cmd,
        base_tags=base_tags,
        base_variant=config.get('base_variant', {}),
        coerce_negative_duration=config.get('coerce_negative_duration', True),
        test_id_prefix=config.get('test_id_prefix', ''),
        test_location_base=config.get('test_location_base'),
        location_tags_file=config.get('location_tags_file'),
        require_build_inv=True,
        exonerate_unexpected_pass=config.get('exonerate_unexpected_pass', True),
    )
    # Even rdb failed we should complete the test runner build, so that
    # the we could return the stainless log link to upstream builders.
    try:
      if stainless_url:
        self._upload_invocation_artifacts(stainless_url)
      return self.m.step('run rdb', cmd)
    except self.m.step.StepFailure:
      self.m.step.active_result.presentation.status = self.m.step.WARNING
    return

  def _ensure_result_adapter_executables(self):
    """Ensure the result_adapter CLI is installed."""
    if self._result_adapter:
      return
    version = 'staging' if self.m.cros_infra_config.is_staging else 'prod'
    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure result_adapter'):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'result_adapter')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('infra/tools/result_adapter/${platform}', version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._result_adapter = cipd_dir.join('result_adapter')

  def _upload_invocation_artifacts(self, stainless_url):
    """Upload artifacts associated with the entire invocation.

    Args:
      stainless_url (string): Link to the Stainless logs for the test run.
    """
    artifact = {'stainless_logs': {'contents': stainless_url}}
    self.m.resultdb.upload_invocation_artifacts(artifact)

  def apply_exonerations(self, invocation_ids, default_behavior=Request.Params
                         .TestExecutionBehavior.BEHAVIOR_UNSPECIFIED,
                         behavior_overrides_map=None):
    """Exonerate unexpected test failures for the given invocations.

    Currently only supports exonerating tests based on criticality.
    First attempt to exonerate based on test run's default behavior. If the
    default behavior is not exonerable, try to apply a test case behavior
    override.

    Args:
      invocation_ids (list(str)): The ids of the invocation whose results we
        should try to exonerate.
      default_behavior (TestExecutionBehavior): The default behavior for all
          tests in the test_runner build.
      behavior_overrides_map (dict{str: TestExecutionBehavior}): Test-specific
          behavior overrides that supersede the default behavior.
    """
    with self.m.step.nest('exonerate ResultDB results') as presentation:

      # If no test execution behavior is specified, assume the tests are
      # critical and therefore not exonerable.
      if not (default_behavior or behavior_overrides_map):
        return

      # ResultDB step failures should not fail the build.
      # TODO(b/206989022): Consider refactoring this to use the exponential
      # retries decorator.
      status = 'SUCCESS'
      for _ in range(2):
        try:
          self._apply_exonerations(
              invocation_ids, default_behavior,
              behavior_overrides_map=behavior_overrides_map or {})
          break
        except self.m.step.StepFailure:
          status = 'WARNING'
      presentation.status = status

  def _apply_exonerations(self, invocation_ids, default_behavior,
                          behavior_overrides_map):

    def _is_exonerable(test_name):
      if default_behavior == TestExecutionBehavior.NON_CRITICAL:
        return True
      test_behavior = behavior_overrides_map.get(
          test_name, TestExecutionBehavior.BEHAVIOR_UNSPECIFIED)
      return test_behavior == TestExecutionBehavior.NON_CRITICAL

    # ResultDB test_id represents the name of the test case.
    inv_bundle = self.m.resultdb.query(inv_ids=invocation_ids,
                                       variants_with_unexpected_results=True,
                                       tr_fields=['variant', 'testId'])

    test_exonerations = []
    for x in inv_bundle.values():
      unexpected_results = x.test_results

      test_exonerations.extend([
          test_result_pb2.TestExoneration(
              test_id=result.test_id, variant=result.variant,
              explanation_html='failed but is not critical')
          for result in unexpected_results
          # Unexpected passes are currently exonerated by default.
          if result.status == test_result_pb2.FAIL and
          _is_exonerable(result.test_id)
      ])
    self.m.resultdb.exonerate(test_exonerations,
                              step_name="exonerate non-critical failures")
