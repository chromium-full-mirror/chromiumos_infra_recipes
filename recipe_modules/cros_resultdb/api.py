# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import base64
import os
import re

from google.protobuf.json_format import MessageToDict, ParseDict

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.resultdb.proto.v1 import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import recorder as recorder_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2
from PB.test_platform.request import Request

TestExecutionBehavior = Request.Params.TestExecutionBehavior

# Map of TestExecutionBehaviors and their priority where a higher value equals a
# higher priority. When multiple TestExecutionBehaviors apply to a single test
# result the TestExecutionBehavior with the highest ordering takes precedence.
TEST_EXEC_BEHAVIOR_ORDERING = {
    TestExecutionBehavior.BEHAVIOR_UNSPECIFIED: 0,
    TestExecutionBehavior.CRITICAL: 1,
    TestExecutionBehavior.NON_CRITICAL: 2,
}

RESULT_ADAPTER_FORMATS = [
    'gtest', 'json', 'single', 'tast', 'skylab-test-runner'
]


class ResultDBCommand(recipe_api.RecipeApi):
  """Module for chromium tests on skylab to upload result to Result DB."""

  def __init__(self, **kwargs):
    super(ResultDBCommand, self).__init__(**kwargs)
    self._result_adapter = None

  @property
  def current_invocation_id(self):
    """Return the current invocation's id."""
    if not self.m.resultdb.enabled:
      return

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
      result_format = config.get('result_format')
      artifact_directory = config.get('artifact_directory')
      if result_format in {'tast', 'gtest'}:
        config['result_file'] = self.get_drone_result_file(
            base_dir, result_format)
        config['artifact_directory'] = self.get_drone_artifact_directory(
            base_dir, result_format,
            artifact_directory) or config.get('artifact_directory')
      return self._upload(config)

  def get_drone_result_file(self, base_dir, result_format):
    """Get the path to the test results file on the drone.

    There are hardcoded for tast and gtest in this module.

    Args:
      base_dir (Path): The path of the base test results on the drone server.
          For example, Chromium gtest result can be found at
          base_dir/autoserv_test/chromium/results.
      result_format (str): The format of the test results.

    Returns:
      Path to the test results file on the drone server.
    """
    # Test results on Drone server are not stored in swarming [start_dir],
    # e.g. "/usr/local/autotest/results/swarming-12345678/1".
    # So use general os.path to join.
    base = os.path.join(base_dir, 'autoserv_test')
    result_file_by_type = {
        'gtest': os.path.join(base, 'chromium/results/output.json'),
        'tast': os.path.join(base, 'tast/results/streamed_results.jsonl'),
    }
    return result_file_by_type.get(result_format)

  def get_drone_artifact_directory(self, base_dir, result_format=None,
                                   artifact_directory=''):
    """Get the path to the test results artifact directory on the drone.

    Currently only supports Tast and Gtest.

    Args:
      base_dir (Path): The path of the base test results on the drone server.
          For example, Chromium gtest result can be found at
          base_dir/autoserv_test/chromium/results.
      result_format (str): The format of the test results.
      artifact_directory (Path): rel path relative to autotest result folder.
          ONLY for gtest, E.g. chromium/debug. For tast test, we rely on
          it to pass the runtime result path to adapter. So we do
          not accept user defined artifact fed to this module.

    Returns:
      Path to the test results artifact directory on the drone server.
    """
    base = os.path.join(base_dir, 'autoserv_test')
    if result_format == 'tast':
      return base
    return os.path.join(base, artifact_directory)

  def upload(self, config, stainless_url=None,
             step_name='upload test results to rdb'):
    """Wrapper for uploading test results to resultDB.

    Args:
      config (dict) A dict wrapping all resultdb parameters.
      stainless_url (string): Link to the Stainless logs for the test run.
      step_name (str): The name of the step or None for default.
    """
    with self.m.step.nest(step_name):
      return self._upload(config, stainless_url)

  def _upload(self, config, stainless_url=None):
    """Call the ResultDB module to upload test result

    Args:
      config (dict) A dict wrapping all resultdb parameters. For a list of
          supported parameters refer to the recipe_engine/resultdb module.
      stainless_url (string): Link to the Stainless logs for the test run.
    """
    pres = self.m.step.active_result.presentation
    if not self.m.resultdb.enabled:
      pres.step_text = 'resultdb is not enabled on this builder'
      pres.status = self.m.step.WARNING
      return
    if config.get('result_format') not in RESULT_ADAPTER_FORMATS:
      pres.step_text = 'result_format must be one of %s got %s' % (
          ', '.join(RESULT_ADAPTER_FORMATS), config.get('result_format'))
      pres.status = self.m.step.WARNING
      return

    # ResultDB in CrOS recipes only supports uploading result file,
    # so the cmd must accompany the result_adapter.
    self._ensure_result_adapter_executables()
    result_adapter = [
        self._result_adapter,
        config.get('result_format'),
        '-result-file',
        config.get('result_file'),
    ]
    if config.get('artifact_directory'):
      result_adapter += [
          '-artifact-directory',
          config.get('artifact_directory')
      ]

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
                         behavior_overrides_map=None, variant_filter=None):
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
      variant_filter (dict): Attributes which must all be present in the test
          result variant definition in order to exonerate.
    """
    with self.m.step.nest('exonerate ResultDB results') as presentation:

      if not (self.m.resultdb.enabled and invocation_ids):
        return

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
              behavior_overrides_map=behavior_overrides_map or {},
              variant_filter=variant_filter or {})
          break
        except self.m.step.StepFailure:
          status = 'WARNING'
      presentation.status = status

  def _apply_exonerations(self, invocation_ids, default_behavior,
                          behavior_overrides_map, variant_filter):

    def _test_exec_behavior(test_name):
      override_behavior = behavior_overrides_map.get(
          test_name, TestExecutionBehavior.BEHAVIOR_UNSPECIFIED)
      return max(TEST_EXEC_BEHAVIOR_ORDERING[default_behavior],
                 TEST_EXEC_BEHAVIOR_ORDERING[override_behavior])

    def _is_exonerable(test_result):
      test_exec_behavior = _test_exec_behavior(test_result.test_id)
      is_non_critical = test_exec_behavior == TestExecutionBehavior.NON_CRITICAL

      # A test results's variant must contain all attributes of the
      # variant_filter.
      variant = MessageToDict(test_result.variant).get('def', {})
      contains_variant_filter = set(variant_filter.items()) <= set(
          variant.items())

      return is_non_critical and contains_variant_filter

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
          if result.status == test_result_pb2.FAIL and _is_exonerable(result)
      ])
    self.m.resultdb.exonerate(test_exonerations,
                              step_name="exonerate non-critical failures")

  def report_missing_test_cases(self, test_names, base_variant):
    """Upload test results for missing test cases to ResultDB.

    Args:
      test_names (str): The names of the tests that should have run but did not.
      base_variant (dict): Variant key-value pairs to attach to the test
          results.
    """
    if not self.m.resultdb.enabled:
      return

    # Return early if there are no missing tests.
    if not test_names:
      return

    variant = ParseDict({'def': base_variant},
                        common_pb2.Variant()) if base_variant else None
    reqs = []
    for test in test_names:
      test_result = test_result_pb2.TestResult(
          test_id=test, result_id=str(self.m.buildbucket.build.id),
          status=test_result_pb2.SKIP, expected=False, variant=variant)
      test_result_req = recorder_pb2.CreateTestResultRequest(
          invocation=self.m.resultdb.current_invocation,
          test_result=test_result)
      reqs.append(test_result_req)
    req = recorder_pb2.BatchCreateTestResultsRequest(
        invocation=self.m.resultdb.current_invocation, requests=reqs)

    step_test_data = self.m.json.dumps({
        'testResults': [{
            'name':
                '%s/test/%s/results/%s' %
                (self.m.resultdb.current_invocation, test,
                 str(self.m.buildbucket.build.id)),
            'resultId':
                str(self.m.buildbucket.build.id),
            'status':
                'SKIP',
            'testId':
                test,
        } for test in test_names]
    })
    # ResultDB step failures should not fail the build.
    # TODO(b/206989022): Consider refactoring this to use the exponential
    # retries decorator.
    upload_status = 'SUCCESS'
    for _ in range(2):
      try:
        self.m.resultdb._rpc(  # pylint: disable=protected-access
            'upload missing test cases', 'luci.resultdb.v1.Recorder',
            'BatchCreateTestResults', req=MessageToDict(req),
            include_update_token=True, step_test_data=lambda: self.m.raw_io.
            test_api.stream_output(step_test_data))
        break
      except self.m.step.StepFailure:
        upload_status = 'WARNING'
    self.m.step.active_result.presentation.status = upload_status
