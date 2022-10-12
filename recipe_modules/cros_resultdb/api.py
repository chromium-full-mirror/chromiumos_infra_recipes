# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import base64
import os
import re

import six
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf import field_mask_pb2

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.resultdb.proto.v1 import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import recorder as recorder_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2
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

# Max size allowed is 500. Keeping it 490 to be safer.
RPC_BATCH_SIZE = 490


class ResultDBCommand(recipe_api.RecipeApi):
  """Module for chromium tests on skylab to upload result to Result DB."""

  def __init__(self, **kwargs):
    super(ResultDBCommand, self).__init__(**kwargs)
    self._result_adapter = None

  @property
  def current_invocation_id(self):
    """Return the current invocation's id."""
    if not self.m.resultdb.enabled:
      return None

    inv_id = self.m.resultdb.invocation_ids(
        [self.m.resultdb.current_invocation])
    return str(inv_id[0])

  def export_invocation_to_bigquery(self, bigquery_exports=None):
    """Modifies the current invocation to be exported to BigQuery (along with
    its children) once it is finalized.

    This should only be called on top level invocations, if it is called on a
    parent and a child, all test results in the child will be exported twice.

    Note that this should normally be configured on the builder definition in
    infra/config rather than in the recipe.  Only use this when a builder
    cannot be determined to always export to Bigquery at configuration time,
    but needs to determine it at recipe runtime.

    Args:
      bigquery_exports (list(resultdb.BigQueryExport)): The BigQuery export
      configurations of tables and predicates of what to export.
    """
    if not self.m.resultdb.enabled or not bigquery_exports:
      return

    inv = invocation_pb2.Invocation(name=self.m.resultdb.current_invocation,
                                    bigquery_exports=bigquery_exports)
    update_mask = field_mask_pb2.FieldMask(paths=['bigquery_exports'])
    req = recorder_pb2.UpdateInvocationRequest(invocation=inv,
                                               update_mask=update_mask)
    # TODO(mwarton): move this method implementation to the resultdb API class
    # (in chromium src) once it is tested and verified to be working.
    self.m.resultdb._rpc(  # pylint: disable=protected-access
        "mark resultdb invocation for bigquery export",
        "luci.resultdb.v1.Recorder", "UpdateInvocation", MessageToDict(req),
        include_update_token=True,
        step_test_data=lambda: self.m.json.test_api.output_stream({}))

  def extract_chromium_resultdb_settings(self, test_args):
    """Extract resultdb settings from test_args for chromium test results.

    Extracts resultdb settings from test_args. Also converts base_tags from a
    list of strings ['key:value'] into a list of string tuples [(key, value)] as
    is expected by resultdb.wrap().

    Args:
      test_args (string): Extra autotest arguments, e.g. "key1=val1 key2=val2".
          Chromium tests use test_arg to pass runtime parameters to our autotest
          wrapper. We reuse it to pipe resultDB arguments, because it is easy to
          access in the test runner recipe. test_args must contain
          resultdb_settings which is base64 compressed json string, wrapping all
          resultdb parameters.

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

    rdb_config = self.m.json.loads(six.ensure_str(rdb_settings))
    rdb_config['base_tags'] = [
        tuple(x.split(':', 1)) for x in rdb_config.get('base_tags', [])
    ]
    return rdb_config

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
      self._upload(config, stainless_url)

  def _upload(self, config, stainless_url=None):
    """Call the ResultDB module to upload test result

    Args:
      config (dict) A dict wrapping all resultdb parameters. For a list of
          supported parameters refer to the recipe_engine/resultdb module.
      stainless_url (string): Link to the Stainless logs for the test run.
    """
    pres = self.m.step.active_result.presentation
    pres.logs['config'] = self.m.json.dumps(config, indent=4)
    if not self.m.resultdb.enabled:
      pres.step_text = 'resultdb is not enabled on this builder'
      pres.status = self.m.step.FAILURE
      return
    if config.get('result_format') not in RESULT_ADAPTER_FORMATS:
      pres.step_text = 'result_format must be one of %s got %s' % (
          ', '.join(RESULT_ADAPTER_FORMATS), config.get('result_format'))
      pres.status = self.m.step.FAILURE
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

    realm = ''
    board = ''
    model = ''
    base_tags = config.get('base_tags', [])
    for tag in base_tags:
      k, v = tag
      if k == 'board':
        board = v
      if k == 'model':
        model = v
    # TODO(b/251688396): remove this hardcoded model for testing and replace
    # with a general solution for all models.
    if board == 'brya' and model == 'taeko':
      realm = 'chromeos:brya-taeko'

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
        include=(realm != ''),
        realm=realm,
    )
    # Even rdb failed we should complete the test runner build, so that
    # the we could return the stainless log link to upstream builders.
    try:
      if stainless_url:
        self._upload_invocation_artifacts(stainless_url)
      self.m.step('run rdb', cmd)
    except self.m.step.StepFailure:
      self.m.step.active_result.presentation.status = self.m.step.FAILURE
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
    artifact = {
        'stainless_logs': {
            'contents': six.ensure_binary(stainless_url)
        }
    }
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

    def _is_non_critical(test_result):
      test_exec_behavior = _test_exec_behavior(test_result.test_id)
      is_non_critical = test_exec_behavior == TestExecutionBehavior.NON_CRITICAL

      # A test results's variant must contain all attributes of the
      # variant_filter.
      variant = MessageToDict(test_result.variant).get('def', {})
      contains_variant_filter = set(variant_filter.items()) <= set(
          variant.items())

      return is_non_critical and contains_variant_filter

    # ResultDB test_id represents the name of the test case.
    inv_bundle = self.m.resultdb.query(
        inv_ids=invocation_ids, variants_with_unexpected_results=True,
        tr_fields=['variant', 'testId', 'status', 'expected'])

    test_exonerations = []
    for x in inv_bundle.values():
      unexpected_results = x.test_results

      test_exonerations.extend([
          test_result_pb2.TestExoneration(
              test_id=result.test_id, variant=result.variant,
              explanation_html='unexpectedly skipped but is not critical'
              if result.status == test_result_pb2.SKIP else
              'failed but is not critical',
              reason=test_result_pb2.ExonerationReason.NOT_CRITICAL)
          for result in unexpected_results
          # Unexpected passes are currently exonerated by default.
          if not result.expected and result.status != test_result_pb2.PASS and
          _is_non_critical(result)
      ])
    self.m.resultdb.exonerate(test_exonerations,
                              step_name="exonerate non-critical failures")

  def apply_exonerated_exonerations(self, invocation_ids):
    """Exonerate already exonerated test failures for the given invocations.

    Args:
      invocation_ids (list(str)): The ids of the invocation whose results we
        should try to exonerate.
    """
    if not (self.m.resultdb.enabled and invocation_ids):
      return

    def _is_exonerated(test_result):
      return self.m.exonerate.is_exonerated(test_result)

    # ResultDB test_id represents the name of the test case.
    inv_bundle = self.m.resultdb.query(
        inv_ids=invocation_ids, variants_with_unexpected_results=True,
        tr_fields=['variant', 'testId', 'status', 'expected'])

    test_exonerations = []
    for x in inv_bundle.values():
      unexpected_results = x.test_results

      test_exonerations.extend([
          test_result_pb2.TestExoneration(
              test_id=result.test_id, variant=result.variant,
              explanation_html='failed but is exonerated',
              reason=test_result_pb2.ExonerationReason.OCCURS_ON_OTHER_CLS)
          for result in unexpected_results
          # Unexpected passes are currently exonerated by default.
          if not result.expected and result.status not in (
              test_result_pb2.PASS,
              test_result_pb2.SKIP) and _is_exonerated(result)
      ])

    try:
      # Don't fail orchestrator if exonerate cmd fails.
      self.m.resultdb.exonerate(test_exonerations,
                                step_name="exonerate exonerated failures")
    except self.m.step.StepFailure:
      pass

  def report_missing_test_cases(self, test_names, base_variant):
    """Upload test results for missing test cases to ResultDB. These missing
    test cases should have run but did not unexpectedly, so their result
    status is marked as SKIP and the expected field is False.

    Args:
      test_names (str[]): The names of the tests that should have run but did
          not.
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
    reqs_list = []
    for test in test_names:
      test_result = test_result_pb2.TestResult(
          test_id=test, result_id=str(self.m.buildbucket.build.id),
          status=test_result_pb2.SKIP, expected=False, variant=variant)
      test_result_req = recorder_pb2.CreateTestResultRequest(
          invocation=self.m.resultdb.current_invocation,
          test_result=test_result)
      reqs_list.append(test_result_req)

    # TODO(b/217973414): Remove custom sorting of results after py2 testing
    # is disabled.
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
            'expected':
                False,
            'testId':
                test,
        } for test in sorted(test_names)]
    })

    batched_reqs = [
        reqs_list[i:i + RPC_BATCH_SIZE]
        for i in range(0, len(reqs_list), RPC_BATCH_SIZE)
    ]
    for reqs in batched_reqs:
      req = recorder_pb2.BatchCreateTestResultsRequest(
          invocation=self.m.resultdb.current_invocation, requests=reqs)

      # ResultDB step failures should not fail the build.
      # TODO(b/206989022): Consider refactoring this to use the exponential
      # retries decorator.
      upload_status = 'SUCCESS'
      for _ in range(2):
        try:
          # TODO(mwarton): move this method implementation to the resultdb API class
          # (in chromium src) once it is tested and verified to be working. pylint
          # disable is here to enable upload of WIP CL.
          # TODO(b/217973414): Remove custom sorting of results after py2 testing
          # is disabled.
          normalized_req = MessageToDict(req)
          normalized_req['requests'].sort(
              key=lambda x: x['testResult']['testId'])
          self.m.resultdb._rpc(  # pylint: disable=protected-access
              'upload missing test cases (count: {})'.format(len(reqs)),
              'luci.resultdb.v1.Recorder', 'BatchCreateTestResults',
              req=normalized_req, include_update_token=True,
              step_test_data=lambda: self.m.raw_io.test_api.stream_output_text(
                  step_test_data))
          break
        except self.m.step.StepFailure:
          upload_status = 'WARNING'
      self.m.step.active_result.presentation.status = upload_status
