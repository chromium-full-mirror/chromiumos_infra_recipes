# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros_resultdb is a module to ease interaction with ResultDB for ChromeOS.  It
extends the functionality in the resultdb module with ChromeOS scpecific
utilities."""
import base64
import os
import re

from google.protobuf import field_mask_pb2
from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import ParseDict

from PB.go.chromium.org.luci.resultdb.proto.v1 import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import recorder as recorder_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2
from PB.test_platform.request import Request
from recipe_engine import recipe_api

TestExecutionBehavior = Request.Params.TestExecutionBehavior
TestResultVisibility = Request.Params.ResultsUploadConfig.TestResultsUploadVisibility

# Map of TestExecutionBehaviors and their priority where a higher value equals a
# higher priority. When multiple TestExecutionBehaviors apply to a single test
# result the TestExecutionBehavior with the highest ordering takes precedence.
TEST_EXEC_BEHAVIOR_ORDERING = {
    TestExecutionBehavior.BEHAVIOR_UNSPECIFIED: 0,
    TestExecutionBehavior.CRITICAL: 1,
    TestExecutionBehavior.NON_CRITICAL: 2,
}

RESULT_ADAPTER_FORMATS = [
    'gtest', 'json', 'single', 'tast', 'skylab-test-runner', 'native'
]

# Max size allowed is 500. Keeping it 490 to be safer.
RPC_BATCH_SIZE = 490


class ResultDBCommand(recipe_api.RecipeApi):
  """Module for chromium tests on skylab to upload result to Result DB."""

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
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
        'mark resultdb invocation for bigquery export',
        'luci.resultdb.v1.Recorder', 'UpdateInvocation', MessageToDict(req),
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

    rdb_config = self.m.json.loads(rdb_settings.decode())
    rdb_config['base_tags'] = [
        tuple(x.split(':', 1)) for x in rdb_config.get('base_tags', [])
    ]
    return rdb_config

  def get_drone_result_file(self, base_dir, result_format,
                            autotest_name='chromium', is_cft=False):
    """Get the path to the test results file on the drone.

    There are hardcoded for tast and gtest in this module.

    Args:
      base_dir (Path): The path of the base test results on the drone server.
          For example, Chromium gtest result can be found at
          base_dir/autoserv_test/chromium/results.
      result_format (str): The format of the test results.
      autotest_name: The autotest name for non-tast tests. By default,
          it is 'chromium', the generic wrapper name for browser gtests.
      is_cft (bool): True if it's for CFT test results.

    Returns:
      Path to the test results file on the drone server.
    """
    # Test results on Drone server are not stored in swarming [start_dir],
    # e.g. "/usr/local/autotest/results/swarming-12345678/1".
    # So use general os.path to join.
    # TODO(b/307657497): Remove is_cft filter and the `autoserv_test` prefix
    # once the CFT migration is done.
    base = os.path.join(base_dir, 'autoserv_test' if is_cft is False else '')
    result_file_by_type = {
        'gtest':
            os.path.join(base, '{}/results/output.json'.format(autotest_name)),
        'native':
            os.path.join(
                base, '{}/results/native_results.jsonl'.format(autotest_name)),
        'tast':
            os.path.join(base, 'tast/results/streamed_results.jsonl'),
    }
    return result_file_by_type.get(result_format)

  def get_drone_artifact_directory(self, base_dir, result_format=None,
                                   artifact_directory='', is_cft=False):
    """Get the path to the test results artifact directory on the drone.

    Currently only supports Tast and Gtest.

    Args:
      base_dir (str): The path of the base test results on the drone server.
          For example, Chromium gtest result can be found at
          base_dir/autoserv_test/chromium/results.
      result_format (str): The format of the test results.
      artifact_directory (str): rel path relative to autotest result folder.
          ONLY for gtest, E.g. chromium/debug. For tast test, we rely on
          it to pass the runtime result path to adapter. So we do
          not accept user defined artifact fed to this module.
      is_cft (bool): True if it's for CFT test results.

    Returns:
      Path to the test results artifact directory on the drone server.
    """
    # TODO(b/307657497): Remove is_cft filter and the `autoserv_test` prefix
    # once the CFT migration is done.
    base = os.path.join(base_dir, 'autoserv_test' if is_cft is False else '')
    if artifact_directory is None or result_format == 'tast':
      return base
    return os.path.join(base, artifact_directory)

  def upload(self, config, testhaus_url=None,
             step_name='upload test results to rdb'):
    """Wrapper for uploading test results to resultDB.

    Args:
      config (dict) A dict wrapping all resultdb parameters.
      testhaus_url (string): Link to the Testhaus logs for the test run.
      step_name (str): The name of the step or None for default.
    """
    with self.m.step.nest(step_name):
      self._upload(config, testhaus_url)

  def _is_build_partner_visible(self, board, image):
    """Returns True if a build is visible to partners or False otherwise.

    A build is partner visible if it's a base or allowlisted variant build.

    Examples:
      "brya-cq/R11-123.45" is a base build
      "brya-kernelnext-cq/R11-123.45" is a variant build

    The variant build is verified by the board variants which are maintained in
    an explicit allowlist in case there are any variants that represent
    super-secret Google projects.

    Note that the input board is a basic board, and only the input image will
    include the board variant name if it's a variant.

    Args:
      board (str): e.g. "brya"
      image (str): e.g. "brya-cq/R11-123.45"
    """
    # Matches the base board name and fetches the variant suffix if it exists.
    board_variant_allowlist = set([
        '64',
        '-arc-r',
        '-arc-s',
        '-arc-t',
        '-borealis',
        '-kernelnext',
        '-manatee-kernelnext',
        '-userdebug',
    ])
    build_re = re.compile(r'^{}(.*)-[a-z]+/R[0-9.\-]+$'.format(board))
    match = re.match(build_re, image)
    if not match:
      return False

    # Checks if it's a base build or an allowlisted variant build.
    variant = match.group(1)
    return not variant or variant in board_variant_allowlist

  def _get_board_model_realm(self, base_tags, skip_board_model_check):
    """Gets the board-model realm for this test result.

    Returns '' if no appropriate board-model realm was found.

    Args:
      base_tags (list): A list of tags for the build.
      skip_board_model_check (bool): Whether the board-model realm should be
        verified against an internal realms list.
    """
    board = ''
    model = ''
    image = ''
    multiduts = ''
    for tag in base_tags:
      k, v = tag
      if k == 'board':
        board = v
      if k == 'model':
        model = v
      if k == 'image':
        image = v
      if k == 'multiduts':
        multiduts = v

    # Exit early if we don't know the board, model, or image.
    if board == '' or model == '' or image == '':
      return ''

    # Don't use the board-model realm unless it is a base or allowlisted variant
    # build.
    # Note that variant builds also will be associated with board-model realm
    # instead of board-variant-model realm which isn't supported.
    if not self._is_build_partner_visible(board, image):
      return ''

    # If the test is a multi-DUT test, don't use the board-model realm.
    # TODO(b/251688396): Handle multi-DUT tests.
    if multiduts == 'True':
      return ''

    realm = '{}-{}'.format(board, model)

    if not skip_board_model_check:
      available_realms = self.m.cros_infra_config.get_realms_list()

      if not realm in available_realms:
        return ''

    return 'chromeos:' + realm

  def _get_partner_vm_realm(self, base_tags):
    """Gets the partner vm realm for this test result.

    Returns '' if the vm board is not allowed to share with partners.

    Args:
      base_tags (list): A list of tags for the build.
    """
    # Returns early if vm test results are for staging testing.
    image = self._extract_tag_value(base_tags, 'image')
    parts = image.split('-')
    if len(parts) == 0 or parts[0] == 'staging':
      return ''

    # The partner vm realm for vm test results which are shared with all
    # ChromeOS partners.
    partner_vm_realm = 'chromeos:partner-vmtest'
    base_vm_board_allowlist = set([
        'amd64-generic',
        'betty',
    ])

    # Checks base vm boards (e.g. 'betty') or vm board variants
    # (e.g. 'betty-arc-r').
    board = self._extract_tag_value(base_tags, 'board')
    parts = board.split('-')
    if board in base_vm_board_allowlist or \
      (len(parts) > 0 and parts[0] in base_vm_board_allowlist):
      return partner_vm_realm

    return ''

  def _extract_tag_value(self, base_tags, tag):
    """Extracts the value for given tag from the base tags

    Returns an empty string if the given tag doesn't exist.

    Args:
      base_tags (list): A list of tags for the build.
      tag (string): The tag name.
    """
    for base_tag in base_tags:
      k, v = base_tag
      if k == tag:
        return v
    return ''

  def _remove_invalid_tags(self, base_tags):
    """Remove the invalid RDB tags.

    Valid tags should follow the following requirements:
    - Tag key regex: ^[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)*$
    - Tag value max length: 256

    See StringPair message for more details:
    https://source.chromium.org/chromium/infra/infra_superproject/+/main:infra/go/src/go.chromium.org/luci/resultdb/proto/v1/common.proto;l=56-64

    Args:
      base_tags (list): A list of tags for the build.
    """
    if base_tags is None:
      return

    invalid_tags = {}
    tag_pattern = '^[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)*$'
    for tag in base_tags.copy():
      k, v = tag
      if not re.match(tag_pattern, k) or len(v) > 256:
        base_tags.remove(tag)
        invalid_tags[k] = v

    if len(invalid_tags) == 0:
      return

    with self.m.step.nest('remove invalid rdb tags') as presentation:
      presentation.logs['invalid_tags'] = invalid_tags
      presentation.status = 'WARNING'

  def _upload(self, config, testhaus_url=None):
    """Call the ResultDB module to upload test result

    Args:
      config (dict) A dict wrapping all resultdb parameters. For a list of
          supported parameters refer to the recipe_engine/resultdb module.
      testhaus_url (string): Link to the Testhaus logs for the test run.
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
    if config.get('test_metadata_file'):
      result_adapter += [
          '-test-metadata-file',
          config.get('test_metadata_file')
      ]
    if testhaus_url and config.get('result_format') != 'tast':
      testhaus_url_str = bytes.decode(testhaus_url) if isinstance(
          testhaus_url, bytes) else testhaus_url
      result_adapter += [
          '-invocation-link-artifacts',
          'testhaus_logs=' + testhaus_url_str,
      ]
    if testhaus_url and config.get('result_format') == 'tast':
      testhaus_url_str = bytes.decode(testhaus_url) if isinstance(
          testhaus_url, bytes) else testhaus_url
      result_adapter += [
          '-testhaus-base-url',
          testhaus_url,
      ]

    # Upload invocation level artifacts if either the config or the builder
    # experiments contain the flag.
    if config.get(
        'invocation_artifacts_upload_to_rdb'
    ) or 'chromeos.cros_infra_config.invocation_artifacts_upload_to_rdb' in self.m.cros_infra_config.experiments:
      result_adapter += [
          '-enable-invocation-artifacts-upload',
          'true',
      ]

    # Skylab tests are running in a SSP container, hence the artifact
    # path has a constant prefix of the container. Instruct the result
    # adapters to ignore it.
    # TODO(crbug/1406710): Extend this flag to all adapters. As of 23Q1
    # browser GPU test is the only user.
    if config.get('result_format') == 'native':
      result_adapter.extend([
          '-trim-artifact-prefix',
          '/usr/local/autotest/results/lxc_job_folder',
      ])

    # Skylab tests can not wrap directly by rdb now. We only care the
    # result file from the test runs.
    rdb_cmd = result_adapter + ['--'] + ['echo']

    base_tags = config.get('base_tags', [])

    # See if this test result should be uploaded into a board-model realm
    # so that partners working on that model can see it.
    realm = ''
    hostname = self._extract_tag_value(base_tags, 'hostname')
    if hostname == 'vm':
      realm = self._get_partner_vm_realm(base_tags)
    else:
      realm = self._get_hardware_realm(config)

    # wrap it with rdb-stream
    self._remove_invalid_tags(base_tags)
    cmd = self.m.resultdb.wrap(
        rdb_cmd,
        base_tags=base_tags,
        base_variant=config.get('base_variant', {}),
        coerce_negative_duration=config.get('coerce_negative_duration', True),
        test_id_prefix=config.get('test_id_prefix', ''),
        test_location_base=config.get('test_location_base'),
        location_tags_file=config.get('location_tags_file'),
        sources_file=config.get('sources_file'),
        sources=config.get('sources'),
        require_build_inv=True,
        exonerate_unexpected_pass=config.get('exonerate_unexpected_pass', True),
        include=config.get('include', False) or (realm != ''),
        realm=realm,
    )
    try:
      self.m.step('run rdb', cmd)
    except self.m.step.StepFailure:
      self.m.step.active_result.presentation.status = self.m.step.FAILURE
    return

  def _get_hardware_realm(self, config):
    """Determine realm for hardware test."""
    base_tags = config.get('base_tags', [])
    result_visibility = config.get(
        'visibility_mode',
        TestResultVisibility.TEST_RESULTS_VISIBILITY_UNSPECIFIED)
    custom_realm = config.get('custom_realm', '')
    skip_board_model_check = config.get('skip_board_model_check')

    if self._should_publish_to_custom_realm(result_visibility, custom_realm):
      realm = custom_realm

      # realm needs to be in form <project>:<realm_name>
      if not realm.startswith('chromeos:'):
        realm = 'chromeos:' + realm
    else:
      realm = self._get_board_model_realm(base_tags, skip_board_model_check)

    return realm

  def _should_publish_to_custom_realm(self, result_visibility, custom_realm):
    """Determine if realm should be a custom, non board/model realm."""
    return result_visibility == TestResultVisibility.TEST_RESULTS_VISIBILITY_CUSTOM_REALM and custom_realm != ''

  def _ensure_result_adapter_executables(self):
    """Ensure the result_adapter CLI is installed."""
    if self._result_adapter:
      return
    version = 'staging' if self.m.cros_infra_config.is_staging else 'prod'
    with self.m.context(infra_steps=True):
      with self.m.step.nest('ensure result_adapter'):
        cipd_dir = self.m.path.start_dir.joinpath('cipd', 'result_adapter')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('infra/tools/result_adapter/${platform}', version)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._result_adapter = cipd_dir / 'result_adapter'

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
                              step_name='exonerate non-critical failures')

  def apply_exonerated_exonerations(self, invocation_ids):
    """Exonerate already exonerated test failures for the given invocations.

    Args:
      invocation_ids (list(str)): The ids of the invocation whose results we
        should try to exonerate.
    """
    if not (self.m.resultdb.enabled and invocation_ids):
      return

    if not self.m.exonerate.is_enabled:
      return

    def _is_exonerated(test_result):
      return self.m.exonerate.is_exonerated(test_result)

    with self.m.step.nest('exonerate exonerated failures') as pres:
      # ResultDB test_id represents the name of the test case.
      inv_bundle = self.m.resultdb.query(
          inv_ids=invocation_ids, variants_with_unexpected_results=True,
          tr_fields=['variant', 'testId', 'status', 'expected'])

      test_exonerations = []
      log_lines = []
      for x in inv_bundle.values():
        unexpected_results = x.test_results

        for result in unexpected_results:
          build_target = getattr(result.variant, 'def')['build_target']
          log_line = '{} on {}: '.format(result.test_id, build_target)
          if result.expected:
            log_line += 'expected result'
          elif result.status in (test_result_pb2.PASS, test_result_pb2.SKIP):
            log_line += 'passed or skipped'
          elif _is_exonerated(result):
            log_line += 'exonerated'
            test_exonerations.append(
                test_result_pb2.TestExoneration(
                    test_id=result.test_id, variant=result.variant,
                    explanation_html='failed but is exonerated',
                    reason=test_result_pb2.ExonerationReason.OCCURS_ON_OTHER_CLS
                ))
          else:
            log_line += 'not exonerated'
          log_lines.append(log_line)

      if log_lines:
        pres.logs['exoneration_logs'] = '\n'.join(log_lines)
      try:
        # Don't fail orchestrator if exonerate cmd fails.
        self.m.resultdb.exonerate(test_exonerations, step_name='exonerate')
      except self.m.step.StepFailure:
        pass

  def report_missing_test_cases(self, test_names, base_variant, base_tags=None):
    """Upload test results for missing test cases to ResultDB. These missing
    test cases should have run but did not unexpectedly, so their result
    status is marked as SKIP and the expected field is False.

    Args:
      test_names (str[]): The names of the tests that should have run but did
          not.
      base_variant (dict): Variant key-value pairs to attach to the test
          results.
      base_tags (list[tuples]): List of tags to attach to the test results.
    """
    if not self.m.resultdb.enabled:
      return

    # Return early if there are no missing tests.
    if not test_names:
      return

    variant = ParseDict({'def': base_variant},
                        common_pb2.Variant()) if base_variant else None

    self._remove_invalid_tags(base_tags)
    tags = [
        common_pb2.StringPair(key=tag[0], value=tag[1]) for tag in base_tags
    ] if base_tags else None

    reqs_list = []
    for test in test_names:
      test_result = test_result_pb2.TestResult(
          test_id=test, result_id=str(self.m.buildbucket.build.id),
          status=test_result_pb2.SKIP, expected=False, variant=variant,
          tags=tags)
      test_result_req = recorder_pb2.CreateTestResultRequest(
          invocation=self.m.resultdb.current_invocation,
          test_result=test_result)
      reqs_list.append(test_result_req)

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
        } for test in test_names]
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
          normalized_req = MessageToDict(req)
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

  def report_filtered_test_cases(self, test_names, base_variant, base_tags=None,
                                 reason='filtered'):
    """Upload test results for filtered test cases to ResultDB.

    These filtered test cases should not run, so their result status
    is marked as SKIP and the expected field is True.

    Args:
      test_names (list[str]): The names of the tests that should not run.
      base_variant (dict): Variant key-value pairs to attach to the test
          results.
      base_tags (list[tuples]): List of tags to attach to the test results.
    """
    if not self.m.resultdb.enabled:
      return

    # Return early if there are no exonerated tests.
    if not test_names:
      return

    variant = ParseDict({'def': base_variant},
                        common_pb2.Variant()) if base_variant else None

    self._remove_invalid_tags(base_tags)
    tags = [
        common_pb2.StringPair(key=tag[0], value=tag[1]) for tag in base_tags
    ] if base_tags else None

    reqs_list = []
    for test in test_names:
      test_result = test_result_pb2.TestResult(
          test_id=test, result_id=str(self.m.buildbucket.build.id),
          status=test_result_pb2.SKIP, expected=True, variant=variant,
          tags=tags, summary_html=reason,
          skip_reason=test_result_pb2.AUTOMATICALLY_DISABLED_FOR_FLAKINESS)
      test_result_req = recorder_pb2.CreateTestResultRequest(
          invocation=self.m.resultdb.current_invocation,
          test_result=test_result)
      reqs_list.append(test_result_req)

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
            'skip_reason':
                'AUTOMATICALLY_DISABLED_FOR_FLAKINESS',
            'summary_html':
                reason,
            'expected':
                True,
            'testId':
                test,
        } for test in test_names]
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
          normalized_req = MessageToDict(req)
          self.m.resultdb._rpc(  # pylint: disable=protected-access
              'upload filtered test cases (count: {})'.format(len(reqs)),
              'luci.resultdb.v1.Recorder', 'BatchCreateTestResults',
              req=normalized_req, include_update_token=True,
              step_test_data=lambda: self.m.raw_io.test_api.stream_output_text(
                  step_test_data))
          break
        except self.m.step.StepFailure:
          upload_status = 'WARNING'
      self.m.step.active_result.presentation.status = upload_status
