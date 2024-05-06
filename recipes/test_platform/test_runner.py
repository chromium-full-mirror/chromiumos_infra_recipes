# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Skylab Test Runner."""
import datetime
import os
import time

import base64
import zlib

from RECIPE_MODULES.chromeos.dut_interface import dut_interface
from RECIPE_MODULES.chromeos.dut_interface import error_messages
from google.protobuf import duration_pb2
from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from PB.chromiumos.build.api import container_metadata
from PB.chromiumos.storage_path import StoragePath
from PB.chromiumos.test import api as ctr_api
from PB.chromiumos.test.api import cros_tool_runner_cli
from PB.chromiumos.test.lab import api as lab_api
from PB.chromiumos.test.lab.api.ip_endpoint import IpEndpoint
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.lucictx import sections as sections_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner \
  import CrosToolRunnerEnvProperties
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner \
  import CrosToolRunnerProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus \
  import PhosphorusEnvProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus \
  import PhosphorusProperties
from PB.recipes.chromeos.test_platform.test_runner import TestRunnerProperties
from PB.test_platform.phosphorus import prejob, runtest, upload_to_gs, fetchcrashes
from PB.test_platform.skylab_local_state import load
from PB.test_platform.common.task import TaskLogData
from PB.test_platform.request import Request as TestPlatformRequest
from PB.test_platform.skylab_test_runner.request import Request
from PB.test_platform.skylab_test_runner.result import Result
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure, RecipeScriptApi
from recipe_engine.recipe_utils import check_type

TestExecutionBehavior = TestPlatformRequest.Params.TestExecutionBehavior

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/random',
    'recipe_engine/raw_io',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'recipe_engine/time',
    'recipe_engine/uuid',
    'cros_infra_config',
    'cros_resultdb',
    'cros_tags',
    'cros_test_runner',
    'cros_tool_runner',
    'cts_results_archive',
    'dut_interface',
    'easy',
    'gcloud',
    'labpack',
    'phosphorus',
    'result_flow',
    'vmlab',
    'urls',
]

MINUTE = 60
HOUR = 60 * MINUTE

PROPERTIES = TestRunnerProperties
_DUMMY_TEST_ID = dut_interface.DUTTestMetadata.DUMMY_TEST_ID
_DUT_STATE_NEEDS_REPAIR = 'needs_repair'
_DUT_STATE_READY = 'ready'
_24_HOURS = 24 * HOUR
_RESULT_PUBLISHING_LIMIT = 15 * MINUTE
_PROVISION_DEADLINE = 45 * MINUTE
TAST_MISSING_TEST_KEY = 'tast_missing_test'
TAST_TEST_NAME_PREFIX = 'tast.'
SOURCES_FILE_NAME = 'sources.jsonpb'

RESULTDB_UPLOAD_STEP = 'Phosphorus: upload to resultdb'


class SourcesNotAvailableException(StepFailure):
  """Raised when the code sources are not available, letting us skip gracefully."""

# API STEP HELPERS
def s_log(step, name, log):
  """Add a `log` to a `step`'s log under `name` is it exists.

  Args:
  * step (StepPresentation): The step to add this log under.
  * name (str): Log name.
  * log (Any): Object to add to log.
  """
  check_type('name', name, str)
  check_type('log', log, (str, type(None)))
  if log:
    step.logs[name] = log


def s_link(step, name, link):
  """Add a link `link` named `link_name` to the `step` if it exists.

  Args:
  * step (StepPresentation): The step to add this link under.
  * name (str): Link name.
  * link (str): Like URI to add.
  """
  check_type('name', name, str)
  check_type('link', link, (str, type(None)))
  if link:
    step.links[name] = link


def _set_step_status(api, step_name, summary, failure_condition=True,
                     fail_build=False):
  """Sets a status for an individual step.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * step_name (str): The name of the new step
  * summary (str): Information for the log.
  * failure_condition (bool): What constitutes a failure in this step.
  * fail_build (bool): If true then will fail build if failure_condition is true.
  """
  check_type('api', api, RecipeScriptApi)
  check_type('step_name', step_name, str)
  check_type('summary', summary, str)
  check_type('failure_condition', failure_condition, bool)
  check_type('fail_build', fail_build, bool)
  with api.step.nest(step_name) as step:
    log = None
    if failure_condition:
      step.status = api.step.FAILURE
      log = summary
    s_log(step=step, name='summary', log=log)
    if fail_build and failure_condition:
      raise api.step.StepFailure(log or '')


def _validate_proto_field(api, proto_object, field_name, fail_build):
  """Validates if field_name exists inside proto_object.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * proto_object (proto): Proto object to validate.
    * field_name (str): The name of the field to validate.
    * fail_build (bool): If true then will fail build on validation failure.
    """
  _set_step_status(api=api, step_name='{} validation'.format(field_name),
                   summary='{} field is missing'.format(field_name),
                   failure_condition=not proto_object.HasField(field_name),
                   fail_build=fail_build)


def validate_request(api, test):
  """Validate the TestRunnerProperties.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * test (Request.Test): Test instance.

    Raises:
      * StepFailure if there are invalid properties.
    """
  with api.step.nest('validate request'):
    if not test.autotest.name:
      raise StepFailure('Test name must be specified')


def archive_all_logs(api, interface, test_metadata, result):
  """Archive all test logs to Google Storage, updating result in the process.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * interface (DUTInterface): The interface to run commands on the DUT.
    * test_metadata (DUTTestMetadata): All metadata needed for the interface
        to access a test.
    * result (DUTResult): The results of the test.

    Raises:
      * InfraFailure if binary call fails.
    """
  with api.context(infra_steps=True):
    with api.step.nest('archive all test logs to Google Storage'):
      interface.upload_to_google_storage(test_metadata)
      if result:
        result.update_log_urls(test_metadata)


def summarize_results_from_phosphorus_results(api, result):
  """Display test cases (and failures) as recipe substeps through the api.

    Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
      * result (DUTResult): The result of all tests.
    """
  with api.step.nest('Results') as step:
    # Do not surface empty link when provision has failure
    if not result.prejob_failed():
      if result.get_testhaus_log_url():
        s_link(step=step, name='Logs in Testhaus',
               link=result.get_testhaus_log_url())
    s_log(step=step, name='JSON output', log=result.to_json())
    for pre_job in result.get_prejob_steps():
      _set_step_status(
          api=api, step_name=pre_job.name,
          summary=pre_job.human_readable_summary,
          failure_condition=pre_job.verdict != Result.Prejob.Step.VERDICT_PASS)
    for test_id, autotest_result in result.get_test_results():
      with api.step.nest(test_id):
        for test_case in autotest_result.test_cases:
          _set_step_status(
              api=api, step_name=test_case.name,
              summary=test_case.human_readable_summary,
              failure_condition=test_case.verdict !=
              Result.Autotest.TestCase.VERDICT_PASS)
      if result.is_test_incomplete():
        _set_step_status(api=api, step_name='autoserv',
                         summary=error_messages.AUTOSERV_CRASH)
    if not result.is_failure():
      if result.prejob_response.is_failure():
        _set_step_status(
            api=api, step_name='prejob execution',
            summary=error_messages.UNSUCCESSFUL_STATE.format(
                result.prejob_response.get_state_name()))
      for failed_test in result.get_failed_tests():
        _set_step_status(
            api=api,
            step_name='test execution for test: {}'.format(failed_test.test_id),
            summary=error_messages.UNSUCCESSFUL_STATE.format(
                failed_test.get_state_name()))


def set_output_properties(api, result):
  """Set the output properties that are part of the test_runner API.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * result (DUTResult): Test results.
    """
  with api.context(infra_steps=True):
    with api.step.nest('set output properties') as step:
      if result is None:
        step.step_text = 'Empty Results'
      else:
        step.properties['compressed_result'] = result.serialize().decode()


def _collect_tests_for_phosphorus(request):
  """Collects tests from Request into one dictionary.

    Args:
    * request (Request): skylab_test_runner request instance.

    Returns:
      dictionary of skylab_test_runner.Request.Test instances
  """
  tests = dict(request.tests)
  if request.HasField('test'):
    tests[_DUMMY_TEST_ID] = request.test
  return tests


def _populate_additional_info_for_autotest_result(test_metadata,
                                                  autotest_result,
                                                  autotest_keyval_file):
  """Populates additional information for autotest results, e.g. full test name,
  timestamps.

  Context: b/244263157, crbug.com/964028

  Args:
  * test_metadata (DUTTestMetadata): All metadata needed for the interface
      to access a test.
  * autotest_result (AutotestProto): The Autotest result for all tests run in
      this run.
  * autotest_keyval_file (dict): The contents for autotest keyval file in logs.

  Returns:
  * autotest_result (AutotestProto): The Autotest result for all tests run in
      this run. Modify the input Autotest result and add additional information.
  """
  # Gets the full test name from the test request.
  full_test_name = test_metadata.test.autotest.name
  for test_case in autotest_result.autotest_result.test_cases:
    # Sets the full test name if necessary.
    if full_test_name and full_test_name.startswith(test_case.name):
      test_case.name = full_test_name

    # Sets the start time and end time.
    if autotest_keyval_file:
      if 'job_started' in autotest_keyval_file:
        test_case.start_time.CopyFrom(
            timestamp_pb2.Timestamp(
                seconds=int(autotest_keyval_file.get('job_started'))))
      if 'job_finished' in autotest_keyval_file:
        test_case.end_time.CopyFrom(
            timestamp_pb2.Timestamp(
                seconds=int(autotest_keyval_file.get('job_finished'))))

  return autotest_result


def _read_autotest_keyval_file(api, autotest_keyval_path):
  """Reads the contents of autotest keyval file.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * autotest_keyval_path (string): The path of the keyval file.

  Returns:
  * autotest_keyval_file (dict): Contents of the autotest keyval file.
  """

  try:
    contents = api.file.read_text('read autotest keyval file',
                                  autotest_keyval_path,
                                  test_data='').splitlines()
    autotest_keyval_file = {}
    for line in contents:
      # Line example: build=zork-cq/R103-14765.0.0-64613-8815327479433497233
      items = line.split('=')
      if len(items) < 2:
        continue
      autotest_keyval_file[items[0]] = items[1]
    return autotest_keyval_file
  except (api.file.Error, FileNotFoundError):
    api.step.active_result.presentation.status = api.step.WARNING
    return {}


def _read_sysinfo_keyvals(api, sysinfo_file_paths):
  """Reads the contents of sysinfo keyval files.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * sysinfo_file_paths (string): The paths to the sysinfo dir.
  Returns:
  * sysinfo_keyvals (dict): Contents of the sysinfo keyval files.
  """
  sysinfo_keyvals = {}
  for path in sysinfo_file_paths:
    _read_kernel_version(api, os.path.join(path, 'uname'), sysinfo_keyvals)
    _read_crossystem_keyvals(api, os.path.join(path, 'crossystem'),
                             sysinfo_keyvals)
    _read_gsctool_keyvals(api, os.path.join(path, 'gsctool'), sysinfo_keyvals)
    _read_servo_keyvals(api, os.path.join(path, 'servo'), sysinfo_keyvals)
  return sysinfo_keyvals


def _read_gsctool_keyvals(api, gsctool_file_path, sysinfo_keyvals):
  """Reads the contents of gsctool keyval file.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * gsctool_file_path (string): The path to the gsctool file.
  * sysinfo_keyvals (dict): Dict to add gsctool keyvals to.
  """
  try:
    contents = api.file.read_text('read gsctool keyval file', gsctool_file_path,
                                  test_data='').splitlines()
    for line in contents:
      # Line examples: "RO 0.0.38", "RW 0.24.13"
      if line.startswith('RO '):
        sysinfo_keyvals['gsc_ro'] = line.split(' ')[1]
      if line.startswith('RW '):
        sysinfo_keyvals['gsc_rw'] = line.split(' ')[1]
  except (api.file.Error, FileNotFoundError):
    api.step.active_result.presentation.status = api.step.WARNING


def _read_servo_keyvals(api, servo_file_path, sysinfo_keyvals):
  """Reads the contents of servo keyval file.

  Example file contents:
  ccd_cr50_version.ccd_flex_secondary=0.6.190/cr50_v3.94_pp.192-3677cf40af
  servo_host_os_version=fizz-labstation-release/R114-15437.59.0
  servo_micro_version.main=servo_micro_v2.4.73-d771c18ba9
  servo_type=servo_v4_with_servo_micro_and_ccd_cr50
  servo_v4_version.root=servo_v4_v2.4.58-c37246f9c
  servod_version=v1.0.1732-67007a28 2023-06-20 19:22:43

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * servo_file_path (string): The path to the servo file.
  * sysinfo_keyvals (dict): Dict to add servo keyvals to.
  """
  try:
    contents = api.file.read_text('read servo keyval file', servo_file_path,
                                  test_data='').splitlines()
    servo_versions = []
    for line in contents:
      items = line.split('=')
      if len(items) < 2:
        continue
      if items[0] == 'servod_version':
        sysinfo_keyvals['servod_version'] = items[1]
      elif items[0] == 'servo_type':
        sysinfo_keyvals['servo_type'] = items[1]
      elif '_version' in items[0] and items[1] != 'None':
        servo_versions.append(items[1])
    if servo_versions:
      sysinfo_keyvals['servo_versions'] = ','.join(servo_versions)
  except (api.file.Error, FileNotFoundError):
    api.step.active_result.presentation.status = api.step.WARNING


def _read_crossystem_keyvals(api, crossystem_file_path, sysinfo_keyvals):
  """Reads the contents of crossystem keyval file.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * crossystem_file_path (string): The path to the crossystem file.
  * sysinfo_keyvals (dict): Dict to add crossystem keyvals to.
  """
  try:
    contents = api.file.read_text('read crossystem keyval file',
                                  crossystem_file_path,
                                  test_data='').splitlines()
    for line in contents:
      # Line example:
      # "fwid = Google_Voema.13672.224.0 # [RO/str] Active firmware ID"
      line = line.split('#')[0].replace(' ', '')
      items = line.split('=')
      if len(items) < 2:
        continue
      if items[0] == 'ro_fwid':
        sysinfo_keyvals['ro_fwid'] = items[1]
      elif items[0] == 'fwid':
        sysinfo_keyvals['rw_fwid'] = items[1]
  except (api.file.Error, FileNotFoundError):
    api.step.active_result.presentation.status = api.step.WARNING


def _read_kernel_version(api, kernel_log_file_path, sysinfo_keyvals):
  """Reads the kernel version from the kernel log file.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * kernel_log_file_path (string): The path to the kernel log file.
  * sysinfo_keyvals (dict): Dict to add kernel version to.
  """
  try:
    # Kernel log file has only 1 line, e.g. "Linux localhost
    # 5.4.151-16902-g93699f4e73de #1 SMPPREEMPT Mon Oct 11 14:52:05 PDT 2021
    # x86_64 Intel(R) Core(TM) i7-7Y75 CPU @ 1.30GHz GenuineIntel GNU/Linux"
    content = api.file.read_text('read kernel log file', kernel_log_file_path,
                                 test_data='')
    if not content:
      return

    items = content.split(' ')
    if len(items) >= 2:
      sysinfo_keyvals['kernel_version'] = items[2]
  except (api.file.Error, FileNotFoundError):
    api.step.active_result.presentation.status = api.step.WARNING


def _read_test_result_file(api, test_result_file_path):
  """Reads the cnotents from the test result file. The contents are different
  for different test harnesses, e.g. Tauto and Tast.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * test_result_file_path (Path): The path to the test result file.
  Returns:
  * content (string): The content of the test results.
  """
  try:
    file_name = api.path.basename(test_result_file_path)
    content = api.file.read_text('read test results from ' + file_name,
                                 test_result_file_path, test_data='')
    return content if content else ''
  except (api.file.Error, FileNotFoundError):
    api.step.active_result.presentation.status = api.step.FAILURE
    return None


def _convert_to_task_request_id(swarming_task_run_id):
  """ Converts the swarming task run id with non "0" suffix to the swarming task
  request id with "0" suffix. Both can be used to point to the same swarming
  task. Swarming supported implicit retry and first task has "1" in suffix and
  retried task has "2" in suffix.

  Args:
  * swarming_task_run_id: The swarming task run id.

  Returns:
  * swarming_task_request_id (string): The swarming task request id.
  """
  if not swarming_task_run_id:
    return ''

  return swarming_task_run_id[:-1] + '0'


def _generate_resultdb_base_tags(api, properties, test_metadata,
                                 autotest_keyval_file, sysinfo_keyvals,
                                 cft_is_enabled):
  """Generate the base tags for the test results.

  This function adds the following tags:
    * image:
        e.g. atlas-kernelnext-release/R105-14989.57.0
    * build:
        e.g. R102-14632.0.0-62834-8818718496810023809
    * declared_name:
        e.g. hatch-cq/R102-14632.0.0-62834-8818718496810023809/wificell-cq/tast.wificell-cq
    * board:
        e.g. hatch
    * model:
        e.g. nipperkin
    * multiduts: whether the test includes multiple duts
        e.g. "True"
    * secondary_boards: secondary boards participating in the multiduts test
        e.g. "brya,pixel5"
    * secondary_models: secondary models participating in the multiduts test
        e.g. "gimble,pixel5a"
    * drone:
        e.g. skylab-drone-deployment-prod-6dc79d4f9-czjlj
    * drone_server:
        e.g. chromeos4-row4-rack1-drone8
    * host_name:
        e.g. chromeos15-row4-rack5-host1
    * queued_time:
        e.g. "2022-06-03 00:15:34.000000 UTC".
    * suite_task_id: The parent's swarming task ID,
        e.g. 59ef5e9532bbd611
    * task_id: The swarming task ID.
        e.g. 59f0e13fe7af0710
    * job_name: The swarming task name (swarming request name),
        e.g. bb-8818737803155059937-chromeos/general/Full
    * logs_url: URL for test result logs,
        e.g. gs://chromeos-test-logs/test-runner/prod/2022-03-26/82df38d1-86fd-42c9-bad5-3e20472cf68a
    * branch:
        e.g. main
    * main_builder_name: Refer to "master_builder_name" in Stainless,
        e.g. master-release
    * ro_fwid: Read-only firmware version,
        e.g. Google_Voema.13672.224.0
    * rw_fwid: Read-write firmware version,
        e.g. Google_Voema.13672.224.0
    * gsc_ro: GSC read-only firmware version,
        e.g. 0.0.38
    * gsc_rw: GSC read-write firmware version,
        e.g. 0.24.13
    * ancestor_buildbucket_ids: All the ancestor buildbucket ids,
        e.g. "8814950840874708945, 8814951792758733697"
    * pool: Device pool, an optional dimension to Swarming, which is used only
        by ChromeOS,
        e.g. "ChromeOSSkylab"
    * label_pool: A pool dimension for swarming task scheduling,
        e.g. "DUT_POOL_QUOTA"
    * wifi_chip: The wifi chip info,
        e.g. "marvell"
    * kernel_version:
        e.g. "5.4.151-16902-g93699f4e73de"
    * hwid_sku:
        e.g. "katsu_MT8183_0B"
    * carrier:
        e.g. "CARRIER_ESIM"
    * ash_version: Ash Chrome browser version,
        e.g. "109.0.5391.0"
    * lacros_version: Lacros browser version,
        e.g. "109.0.5391.0"
    * suite: test suite,
        e.g. "bluetooth_sa"
    * builder_name: build config name,
        e.g. "eve-release"
    * buildbucket_builder: buildbucket builder name,
        e.g. "test runner"
    * servod_version:
        e.g. "v1.0.1732-67007a28 2023-06-20 19:22:43"
    * servo_type:
        e.g. "servo_v4_with_servo_micro_and_ccd_cr50"
    * servo_versions:
        e.g. "servo_v4_v2.4.58-c37246f9c,servo_micro_v2.4.73-d771c18ba9"
    * cbx: CBX label for CBX and non-CBX SKU DUTs. Current values of the label
        are "True" and "False", but in future there might be more values.
        e.g. "True", "False"
    * wifi_router_models: A list of router models within the testbed,
        e.g. "gale"
    * testplan_id: the name of the testplan associated with test runner build
        e.g. "ltl_testplan"
    * chameleon_type: Chameleon type. If multiple labels exist in swarming bot
        dimensions, they will be concatenated by ",",
        e.g. "CHAMELEON_TYPE_HDMI,CHAMELEON_TYPE_V3"
    * qs_account: Quota Scheduler account to use for DUT pool,
        e.g. "unmanaged_p2".
    * ctp_fwd_task_name: Suite scheduler config name,
        e.g. "Bluetooth_Sa_Perbuild".
    * modem_type: modem type of a DUT,
        e.g. "MODEM_TYPE_FIBOCOMM_L850GL".
    * channel: The channel of the builds,
        e.g. "BETA", "DEV", "CANARY", "STABLE".
    * ufs_zone: UFS zone config,
        e.g. "ZONE_SFO36_OS".
    * dlm_sku_id: Identifier set in VPD at factory on new devices which
        correlates to an entry in DLM device SKUs table, should be an integer
        value in the string,
        eg: "12345"
    * chameleon_connection_types: Chameleon connection types, which indicates
        the connection port to the peripherals,
        e.g. "CHAMELEON_CONNECTION_TYPE_USB"

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * properties (TestRunnerProperties): Recipe input properties.
    * test_metadata (DUTTestMetadata): All metadata needed for the interface
        to access a test.
    * autotest_keyval_file (dict): The contents for autotest keyval file in logs.
    * sysinfo_keyvals (dict): The sysinfo keyvals.
    * cft_is_enabled (bool): Whether CFT feature is enabled.

    Returns:
    * base_tags (list[tuples]): Tags for the test results.
  """
  base_tags = []

  # Fetches the following information from buildbucket build tags.
  declared_name = api.cros_tags.get_values('display_name')
  if declared_name:
    base_tags.append(('declared_name', declared_name[0]))

  qs_account = api.cros_tags.get_values('qs_account')
  if qs_account:
    base_tags.append(('qs_account', qs_account[0]))

  ctp_fwd_task_name = api.cros_tags.get_values('ctp-fwd-task-name')
  if ctp_fwd_task_name:
    base_tags.append(('ctp_fwd_task_name', ctp_fwd_task_name[0]))

  channel = api.cros_tags.get_values('branch-trigger')
  if channel:
    base_tags.append(('channel', channel[0]))

  # Get the testplan id (name) from the buildbucket tags.
  testplan_id = api.cros_tags.get_values('test-plan-id')
  if testplan_id:
    base_tags.append(('test_plan_id', testplan_id[0]))

  # Fetches the following information from buildbucket.swarming bot dimensions.
  board = api.cros_tags.get_values('label-board',
                                   api.buildbucket.swarming_bot_dimensions)
  if not board:
    board = api.cros_tags.get_values('label-board')
  if board:
    base_tags.append(('board', board[0]))

  model = api.cros_tags.get_values('label-model',
                                   api.buildbucket.swarming_bot_dimensions)
  if not model:
    model = api.cros_tags.get_values('label-model')
  if model:
    base_tags.append(('model', model[0]))

  # Multi-DUTs support
  multiduts = api.cros_tags.get_values('label-multiduts',
                                       api.buildbucket.swarming_bot_dimensions)
  if multiduts and multiduts[0] == 'True':
    base_tags.append(('multiduts', multiduts[0]))

    # Get the primary & secondary boards and models from the buildbucket tags.
    primary_board = api.cros_tags.get_values('primary_board')
    if primary_board:
      base_tags.append(('primary_board', primary_board[0]))

    primary_model = api.cros_tags.get_values('primary_model')
    if primary_model:
      base_tags.append(('primary_model', primary_model[0]))

    secondary_boards = api.cros_tags.get_values('secondary_boards')
    if secondary_boards:
      base_tags.append(('secondary_boards', secondary_boards[0]))

    secondary_models = api.cros_tags.get_values('secondary_models')
    if secondary_models:
      base_tags.append(('secondary_models', secondary_models[0]))
  else:
    base_tags.append(('multiduts', 'False'))

  chameleon_type = api.cros_tags.get_values(
      'label-chameleon_type', api.buildbucket.swarming_bot_dimensions)
  if chameleon_type:
    base_tags.append(('chameleon_type', ','.join(chameleon_type)))

  drone = api.cros_tags.get_values('drone',
                                   api.buildbucket.swarming_bot_dimensions)
  if drone:
    base_tags.append(('drone', drone[0]))

  drone_server = api.cros_tags.get_values(
      'drone_server', api.buildbucket.swarming_bot_dimensions)
  if drone_server:
    base_tags.append(('drone_server', drone_server[0]))

  hostname = api.cros_tags.get_values('dut_name',
                                      api.buildbucket.swarming_bot_dimensions)
  if hostname:
    base_tags.append(('hostname', hostname[0]))

  pool = api.cros_tags.get_values('pool',
                                  api.buildbucket.swarming_bot_dimensions)
  if pool:
    base_tags.append(('pool', pool[0]))

  # Fetches the label-pool from the requested task dimensions first, and then
  # fall back to the bot dimensions if it doesn't exists.
  label_pool = api.cros_tags.get_values('label-pool',
                                        api.buildbucket.backend_task_dimensions)
  if not label_pool:
    label_pool = api.cros_tags.get_values(
        'label-pool', api.buildbucket.swarming_bot_dimensions)
  if label_pool:
    base_tags.append(('label_pool', label_pool[0]))

  wifi_chip = api.cros_tags.get_values('label-wifi_chip',
                                       api.buildbucket.swarming_bot_dimensions)
  if wifi_chip:
    base_tags.append(('wifi_chip', wifi_chip[0]))

  wifi_router_models = api.cros_tags.get_values(
      'label-wifi_router_models', api.buildbucket.swarming_bot_dimensions)
  if wifi_router_models:
    base_tags.append(('wifi_router_models', wifi_router_models[0]))

  hwid_sku = api.cros_tags.get_values('label-hwid_sku',
                                      api.buildbucket.swarming_bot_dimensions)
  if hwid_sku:
    base_tags.append(('hwid_sku', hwid_sku[0]))

  modem_type = api.cros_tags.get_values('label-modem_type',
                                        api.buildbucket.swarming_bot_dimensions)
  if modem_type:
    base_tags.append(('modem_type', modem_type[0]))

  ufs_zone = api.cros_tags.get_values('ufs_zone',
                                      api.buildbucket.swarming_bot_dimensions)
  if ufs_zone:
    base_tags.append(('ufs_zone', ufs_zone[0]))

  dlm_sku_id = api.cros_tags.get_values('label-dlm_sku_id',
                                        api.buildbucket.swarming_bot_dimensions)
  if dlm_sku_id:
    base_tags.append(('dlm_sku_id', dlm_sku_id[0]))

  cbx = api.cros_tags.get_values('label-cbx',
                                 api.buildbucket.swarming_bot_dimensions)
  if cbx:
    base_tags.append(('cbx', cbx[0]))

  suite_task_id = _convert_to_task_request_id(
      api.buildbucket.swarming_parent_run_id)
  if suite_task_id:
    base_tags.append(('suite_task_id', suite_task_id))

  base_tags.append(
      ('task_id', _convert_to_task_request_id(api.swarming.task_id)))

  # Fetches the following information from buildbucket.build.
  builder_object = api.buildbucket.build.builder
  build_id = str(api.buildbucket.build.id)
  job_name = 'bb-{}-{}/{}/{}'.format(build_id, builder_object.project,
                                     builder_object.bucket,
                                     builder_object.builder)
  base_tags.append(('job_name', job_name))
  base_tags.append(('buildbucket_builder', builder_object.builder))

  queued_time = datetime.datetime.utcfromtimestamp(
      api.buildbucket.build.create_time.seconds)
  base_tags.append(
      ('queued_time', queued_time.strftime('%Y-%m-%d %H:%M:%S.%f UTC')))

  ancestor_buildbucket_ids = ','.join(
      str(id) for id in api.buildbucket.build.ancestor_ids)
  if ancestor_buildbucket_ids:
    base_tags.append(('ancestor_buildbucket_ids', ancestor_buildbucket_ids))

  # Fetches the following information from test_metadata.
  build_tag = ''
  if not cft_is_enabled:
    # Optional tag to help us identify whether tests where run in CFT.
    base_tags.append(('is_cft_run', 'False'))

    # The 'request.prejob.softwareDependencies.chromeosBuild' is from the input
    # properties which is actually used by provisioning and is guaranteed to be
    # present as a result. Example:
    # "octopus-postsubmit/R108-15121.0.0-71034-8802912605960970113"
    software_dependencies = properties.request.prejob.software_dependencies
    if software_dependencies:
      for dep in software_dependencies:
        if dep.WhichOneof('dep') == 'chromeos_build':
          build_tag = dep.chromeos_build
          break
  else:
    base_tags.append(('is_cft_run', 'True'))

    # CFT test request has 'autotest_keyvals' instead of
    # 'prejob.softwareDependencies.chromeosBuild'. CFT test request example:
    # https://logs.chromium.org/logs/chromeos/buildbucket/cr-buildbucket/8802533370122261697/+/u/inputs/cft_test_request
    build_tag = autotest_keyval_file.get('build')
  if build_tag:
    base_tags.append(('image', build_tag))
    base_tags.append(('build', build_tag.split('/')[-1]))

  logs_url = test_metadata.gs_url
  if logs_url:
    base_tags.append(('logs_url', logs_url))

  # Fetches the following information from autotest keyvals.
  suite = autotest_keyval_file.get('suite')
  if not suite:
    # Fallback to Buildbucket tags because CFT test request doesn't populate
    # `suite` in autotest_keyvals.
    suite = api.cros_tags.get_values('suite')[0] if api.cros_tags.get_values(
        'suite') else None
  if suite:
    base_tags.append(('suite', suite))

  builder_name = autotest_keyval_file.get('build_config')
  if builder_name:
    base_tags.append(('builder_name', builder_name))

  branch = autotest_keyval_file.get('branch')
  if branch:
    base_tags.append(('branch', branch))

  main_builder_name = autotest_keyval_file.get('master_build_config')
  if main_builder_name:
    base_tags.append(('main_builder_name', main_builder_name))
  if 'ash_version' in autotest_keyval_file:
    base_tags.append(('ash_version', autotest_keyval_file['ash_version']))
  if 'lacros_version' in autotest_keyval_file:
    base_tags.append(('lacros_version', autotest_keyval_file['lacros_version']))

  if sysinfo_keyvals is not None:
    for key in sysinfo_keyvals:
      base_tags.append((key, sysinfo_keyvals[key]))

  carrier = api.cros_tags.get_values('label-carrier',
                                     api.buildbucket.swarming_bot_dimensions)
  if carrier:
    base_tags.append(('carrier', carrier[0]))

  partner_config = properties.common_config.partner_config
  if partner_config and partner_config.account_id:
    # Sets the partner account id from the common_config.
    # This value is set in the partner luci config file.
    base_tags.append(('account_id', str(partner_config.account_id)))

  chameleon_connection_types = api.cros_tags.get_values(
      'label-chameleon_connection_types',
      api.buildbucket.swarming_bot_dimensions)
  if chameleon_connection_types:
    base_tags.append(
        ('chameleon_connection_types', ','.join(chameleon_connection_types)))

  return base_tags


def _generate_resultdb_variant_def(api, autotest_keyval_file):
  """Generate the variant defintions for the test results.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * autotest_keyval_file (dict): The contents for autotest keyval file in logs.

    Returns:
    * base_variant (dict): Variant attributes for the test results.
    """
  base_variant = {}

  # Fetches the following information from buildbucket build tags.
  board = api.cros_tags.get_values('label-board')
  if board:
    base_variant['board'] = board[0]

  model = api.cros_tags.get_values('label-model')
  if model:
    base_variant['model'] = model[0]

  # Fetches the following information from the autotest.keyvals in the request.
  build_target = autotest_keyval_file.get('build_target')
  if build_target:
    base_variant['build_target'] = build_target

  return base_variant


def _prepare_resultdb_sources_file(api, properties):
  """Fetches information about code sources tested by this execution.

  The code sources typically comprise a git commit (i.e. the CrOS snapshot), as
  well as an optional list of gerrit changes. An is_dirty flag identifies if
  there were other modifications made to the sources (such as if an uncommited
  package uprev being built into the system image or if a custom firmware build
  was used).

  See the luci.resultdb.v1.Sources message for more.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * properties (TestRunnerProperties): Recipe input properties.

  Returns: str: Path to file containing test source information. The file
    will take the form of a JSONPB-serialized luci.resultdb.v1.Sources proto.

  Raises:
  * SourcesNotAvailableException. If the information is not available.
  """

  with api.step.nest('identify sources under test') as step:
    # Google Storage URL to the build.
    build_url = None

    # Whether the image provisioned on the device is a purely the
    # supplied system image, or whether it has additional modifications
    # (e.g. a different Lacros build or firmware).
    is_dirty_provision = False

    if properties.cft_is_enabled:
      provision_state = properties.cft_test_request.primary_dut.provision_state

      # The chromiumos.StoragePath proto describing the path to the build
      # artifacts.
      storage_path = provision_state.system_image.system_image_path
      if storage_path.host_type != StoragePath.HostType.GS:  # pragma: nocover
        raise SourcesNotAvailableException(
            'Code sources metadata file not available for non-GS sources.')
      # The path will be of the form gs://<bucket>/<build>.
      build_url = storage_path.path

      # Custom firmware is being tested.
      if (provision_state.firmware.main_rw_payload.firmware_image_path.path or
          provision_state.firmware.main_ro_payload.firmware_image_path.path):
        is_dirty_provision = True

      # If in future, where custom lacros builds can be deployed via CFT,
      # is_dirty_provision should also be set to true.
    else:
      software_dependencies = properties.request.prejob.software_dependencies
      chromeos_build = None

      # Default to chromeos-image-archive bucket, unless otherwise specified.
      chromeos_build_gcs_bucket = 'chromeos-image-archive'
      if software_dependencies:
        for dep in software_dependencies:
          if dep.WhichOneof('dep') == 'chromeos_build':
            chromeos_build = dep.chromeos_build
          elif dep.WhichOneof('dep') == 'chromeos_build_gcs_bucket':
            chromeos_build_gcs_bucket = dep.chromeos_build_gcs_bucket
          else:  # pragma: nocover
            # Custom Lacros build, or custom firmware.
            is_dirty_provision = True

      if chromeos_build is None:  # pragma: nocover
        step.step_text = 'CrOS build not found in request'
        raise SourcesNotAvailableException('CrOS build not found in request')
      build_url = 'gs://{}/{}'.format(chromeos_build_gcs_bucket, chromeos_build)

    sources_local_path = api.path.join(
        api.path.mkdtemp(prefix='source_metadata'), SOURCES_FILE_NAME)

    # Source information is stored with the build, at
    # /metadata/sources.jsonpb.
    sources_url = api.path.join(build_url, 'metadata', SOURCES_FILE_NAME)
    try:
      # Download the file from Google Stroage.
      gs_step = api.gsutil.download_url(sources_url, sources_local_path,
                                        name='download metadata/sources.jsonpb')
      gs_step.presentation.links[SOURCES_FILE_NAME] = api.urls.get_gs_path_url(
          sources_url)
    except StepFailure as e:
      step.step_text = 'Source information not found'
      step.status = api.step.SUCCESS
      raise SourcesNotAvailableException(
          'sources.jsonpb file not found in GS.') from e

    # Combine is_dirty_provision with the existing is_dirty flag.
    # Both dirty source and dirty provision can make the specification
    # of sources under test incomplete.
    if is_dirty_provision:
      with api.step.nest('mark sources dirty') as step:
        test_sources = invocation_pb2.Sources()
        sources_proto = api.file.read_proto('read sources proto',
                                            sources_local_path,
                                            invocation_pb2.Sources, 'JSONPB',
                                            test_proto=test_sources)

        sources_proto.is_dirty = sources_proto.is_dirty or is_dirty_provision
        api.file.write_proto('write sources proto', sources_local_path,
                             sources_proto, 'JSONPB')

    return str(sources_local_path)


def _upload_missing_tast_results(api, base_variant, base_tags,
                                 autotest_keyval_file):
  """Upload test results for missing Tast test cases to ResultDB.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * base_variant (dict): Variant key-value pairs to attach to the test
            results.
    * base_tags (list[tuples]): List of tags to attach to the test results.
    * autotest_keyval_file (dict): The contents for autotest keyval file
        in logs.
    """
  missing_tests = []
  for key, value in autotest_keyval_file.items():
    if key.startswith(TAST_MISSING_TEST_KEY):
      # Adds the "tast." prefix to Tast test name for convention.
      if not value.startswith(TAST_TEST_NAME_PREFIX):
        value = TAST_TEST_NAME_PREFIX + value
      missing_tests.append(value)
  api.cros_resultdb.report_missing_test_cases(missing_tests, base_variant,
                                              base_tags)


def _upload_autotest_wrapper_result_for_tast(api, test_metadata, result,
                                             autotest_keyval_file, base_variant,
                                             base_tags, skip_board_model_check,
                                             sources_file, visibility_mode,
                                             custom_realm):
  """Upload the Autotest wrapper result for Tast test with base variants and
  base tags. The Autotest wrapper result is captured in the first test case
  after the test execution. An additional tag 'is_control_file_result' will be
  added for the downstream clients to identify.

  Context: b/245017288

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * test_metadata (DUTTestMetadata): All metadata needed for the interface
      to access a test.
  * result (DUTResult): The results of the test.
  * autotest_keyval_file (dict): The contents for autotest keyval file in logs.
  * base_variant (Dict): The dict of base variants for ResultDB results.
  * base_tags (Dict): The dict of base tags for ResultDB results.
  * skip_board_model_check (Bool): If enabled, don't verify board-model realm
      actually exists
  * sources_file (str): Path to a file containing a JSON-serialized
      luci.resultdb.v1.Sources proto describing the code sources being tested.
  * visibility_mode (TestResultsUploadVisibility): Desired visibility of test
      results.
  * custom_realm (str): Name of custom realm to use for test results if
      TestResultsUploadVisibility is set to CUSTOM_REALM.
  """
  try:
    # Skips if it's not a Tast test.
    full_test_name = test_metadata.test.autotest.name
    if full_test_name is None or not full_test_name.startswith(
        TAST_TEST_NAME_PREFIX):
      return

    # Skips if the test execution is incomplete or test case doesn't exist.
    if result.data.autotest_result.incomplete or len(
        result.data.autotest_result.test_cases) == 0:
      return

    # The first test case is named "tast" which is the Autotest wrapper result.
    first_test_case = result.data.autotest_result.test_cases[0]

    # Initializes a new autotest result proto with required fields instead of
    # modifying the original DUT result object directly.
    autotest_result = Result(
        autotest_result=Result.Autotest(test_cases=[
            Result.Autotest.TestCase(
                name=full_test_name,
                verdict=first_test_case.verdict,
                human_readable_summary=first_test_case.human_readable_summary,
            ),
        ]), log_data=result.data.log_data, prejob=result.data.prejob,
        state_update=result.data.state_update)

    # Populates additional info for autotest results that are required by
    # ResultDB upload.
    autotest_result = _populate_additional_info_for_autotest_result(
        test_metadata, autotest_result, autotest_keyval_file)

    # Writes the result to a file which can be parsed by result_adapter.
    temp_dir = api.path.mkdtemp()
    test_result_file = temp_dir / 'autotest_wrapper_tast_result.json'
    api.file.write_proto('write autotest wrapper result for tast',
                         test_result_file, autotest_result, 'JSONPB')

    base_tags.append(('is_control_file_result', 'True'))

    # Uploads test results to ResultDB only when the test result file exists.
    result_file_content = _read_test_result_file(api, test_result_file)
    if result_file_content:
      config = {
          'result_format': 'skylab-test-runner',
          'base_variant': base_variant,
          'base_tags': base_tags,
          'result_file': test_result_file,
          'artifact_directory': None,
          'skip_board_model_check': skip_board_model_check,
          'sources_file': sources_file,
          'visibility_mode': visibility_mode,
          'custom_realm': custom_realm
      }
      api.cros_resultdb.upload(config, str(result.get_testhaus_log_url()))
  except api.step.StepFailure:
    # Marks the step status as Failure only and bypass the exception.
    api.step.active_result.presentation.status = api.step.FAILURE


def _upload_to_resultdb(api, result, properties, interface, test_metadata):
  """Upload test results to ResultDB.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * result (DUTResult): The results of the test.
    * properties (TestRunnerProperties): Recipe input properties.
    * interface (DUTInterface): The interface to run commands on the DUT.
    * test_metadata (DUTTestMetadata): All metadata needed for the interface
        to access a test.
    """
  with api.step.nest(RESULTDB_UPLOAD_STEP) as step:
    if not api.resultdb.enabled:
      s_log(step, 'logging.warning',
            'The resultdb upload is not enabled in this builder.')
      return

    # Don't try to upload if there are no results.
    if not result:
      s_log(step, 'logging.info', 'No test result to upload.')
      return

    # Autotest keyval file is created after test execution `interface.run_test()`
    # is done, so the file needs to be read after test execution.
    base_dir = interface.get_results_directory(test_metadata)
    autotest_keyval_path = os.path.join(base_dir, 'autoserv_test', 'keyval')
    autotest_keyval_file = _read_autotest_keyval_file(api, autotest_keyval_path)

    # TODO(b/200703493): Reconcile Chromium and CrOS test uploads in CTP2.
    if (test_metadata.test.autotest.test_args and
        'resultdb_settings' in test_metadata.test.autotest.test_args):
      # Extract rdb config from test args.
      config = api.cros_resultdb.extract_chromium_resultdb_settings(
          test_metadata.test.autotest.test_args)
      pres = api.step.active_result.presentation
      pres.logs['extracted configs from test_args'] = api.json.dumps(
          config, indent=4)

      # Modify extracted configs if necessary.
      result_format = config.get('result_format')
      artifact_directory = config.get('artifact_directory')
      if result_format in {'tast', 'gtest', 'native'}:
        config['result_file'] = api.cros_resultdb.get_drone_result_file(
            base_dir, result_format,
            autotest_name=test_metadata.test.autotest.name)
        config[
            'artifact_directory'] = api.cros_resultdb.get_drone_artifact_directory(
                base_dir, result_format, artifact_directory)

      # Populate Chromium tast tests with tags.
      if result_format == 'tast':
        sysinfo_file_paths = [
            os.path.join(base_dir, 'autoserv_test', 'sysinfo')
        ]
        sysinfo_keyvals = _read_sysinfo_keyvals(api, sysinfo_file_paths)
        config['base_tags'] = _generate_resultdb_base_tags(
            api, properties, test_metadata, autotest_keyval_file,
            sysinfo_keyvals, cft_is_enabled=False)

      # Upload to rdb using extracted configs.
      api.cros_resultdb.upload(config,
                               step_name='upload chromium test results to rdb')
      # Uploads missing test result for browser tests running with Tauto and
      # Tast
      _upload_missing_tast_results(api, config.get('base_variant'),
                                   config.get('base_tags'),
                                   autotest_keyval_file)
      return

    first_test_case_name = ''
    tast_results_dir = os.path.join(base_dir, 'autoserv_test/tast')
    is_tast_result = os.path.exists(tast_results_dir) or api.properties.get(
        'result_format') == 'tast'
    if is_tast_result:
      result_format = 'tast'
      result_file = api.cros_resultdb.get_drone_result_file(base_dir, 'tast')
      artifact_directory = api.cros_resultdb.get_drone_artifact_directory(
          base_dir, result_format)
    else:
      # Initializes a new autotest result proto with required fields instead of
      # modifying the original DUT result object directly.
      autotest_result = Result(autotest_result=result.data.autotest_result,
                               log_data=result.data.log_data,
                               prejob=result.data.prejob,
                               state_update=result.data.state_update)

      # Populates additional info for autotest results that are required by
      # ResultDB upload.
      autotest_result = _populate_additional_info_for_autotest_result(
          test_metadata, autotest_result, autotest_keyval_file)

      # Writes the result to a file which can be parsed by result_adapter.
      temp_dir = api.path.mkdtemp()
      test_runner_result_file = temp_dir / 'test_runner_result.json'
      api.file.write_proto('write skylab_test_runner result',
                           test_runner_result_file, autotest_result, 'JSONPB')
      result_format = 'skylab-test-runner'
      result_file = test_runner_result_file
      artifact_directory = None

      # Gets the initial test name from the first test case in the iniital result
      # instead of the full test name from the first test case in the modified
      # autotest_result. That's becaise the upstream is still using the initial
      # test name to construct the log artifact directory.
      # The first_test_case_name will be used to read log files below.
      # Context: b/238706967
      for test_case in result.data.autotest_result.test_cases:
        first_test_case_name = test_case.name
        break

    # Fetches rich information from log artifacts.
    # Fallback to the autotest keyval in the input test metadata.
    if not autotest_keyval_file or len(autotest_keyval_file) == 0:
      autotest_keyval_file = test_metadata.test.autotest.keyvals
    # For Tauto, read files from the parent result dir and then the first test
    # case dir if files don't exist because some files might be missing in the
    # parent result dir or in the first test case dir. Thus, we will need to read
    # both places for the worst case.
    # For Tast, read files from the parent result dir only.
    sysinfo_file_paths = [os.path.join(base_dir, 'autoserv_test', 'sysinfo')]
    if first_test_case_name:
      sysinfo_file_paths.append(
          os.path.join(base_dir, 'autoserv_test', first_test_case_name,
                       'sysinfo'))
    sysinfo_keyvals = _read_sysinfo_keyvals(api, sysinfo_file_paths)

    base_variant = _generate_resultdb_variant_def(api, autotest_keyval_file)
    base_tags = _generate_resultdb_base_tags(api, properties, test_metadata,
                                             autotest_keyval_file,
                                             sysinfo_keyvals,
                                             cft_is_enabled=False)

    skip_board_model_check = properties.common_config.skip_board_model_realm_check
    visibility_mode = properties.results_upload_config.mode
    custom_realm = properties.common_config.rdb_config.custom_realm_name

    # Capture the code sources which were tested.
    sources_file = None
    try:
      sources_file = _prepare_resultdb_sources_file(api, properties)
    except SourcesNotAvailableException:  # pragma: nocover
      pass

    config = {
        'result_format': result_format,
        'base_variant': base_variant,
        'base_tags': base_tags,
        'result_file': result_file,
        'artifact_directory': artifact_directory,
        'skip_board_model_check': skip_board_model_check,
        'sources_file': sources_file,
        'visibility_mode': visibility_mode,
        'custom_realm': custom_realm
    }

    # Uploads test results to ResultDB only when the test result file exists.
    result_file_content = _read_test_result_file(api, result_file)
    if result_file_content:
      api.cros_resultdb.upload(config, str(result.get_testhaus_log_url()))

    # Uploads an additional Autotest wrapper result for Tast test.
    if is_tast_result:
      _upload_autotest_wrapper_result_for_tast(api, test_metadata, result,
                                               autotest_keyval_file,
                                               base_variant, base_tags,
                                               skip_board_model_check,
                                               sources_file, visibility_mode,
                                               custom_realm)

    _upload_missing_tast_results(api, base_variant, base_tags,
                                 autotest_keyval_file)
    api.cros_resultdb.apply_exonerations(
        [api.cros_resultdb.current_invocation_id],
        properties.request.default_test_execution_behavior)


def _execution_steps_for_test_with_phosphorus(api, properties, interface,
                                              test_metadata, max_duration_sec,
                                              dut_state, container_image_info,
                                              step):
  """Execute all the required steps for a single test.

  Run the following steps required for a test:
    * Run prejob (prepare machine)
    * Run test
    * Fetch crashes
    * Archive and publish results

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * properties (TestRunnerProperties): recipe input properties.
  * interface (DUTInterface): The interface to run commands on the DUT.
  * test_metadata (DUTTestMetadata): All metadata needed for the interface
        to access a test.
  * max_duration_sec (int): Maximum amount of time the job should run.
  * dut_state (str): The current state of the DUT.
  * container_image_info (ContainerImageInfo): If set, info on a Docker
  container for use by the DUTInterface.
  * step (StepPresentation): The step to add this log under.

  Returns: DUTResult: a constructed result for this test.

  Raises:
  * InfraFailure.
  """
  result = None
  run_test_response = None
  try:
    # prejob and test failures are detected when parsing results.
    # An exception from the steps here indicates an infrastructure
    # failure that should be bubbled up immediately.
    prejob_response = interface.submit_pre_job(test_metadata, max_duration_sec)
    if not prejob_response.is_failure():
      run_test_response = interface.run_test(test_metadata,
                                             container_image_info)
      # TODO(crbug.com/1107005) Once this step is proved stable, stop ignoring
      # errors.
      # TODO(crbug.com/1107005) Add links to UI for the uploaded crashes, using
      # the response from fetch_crashes().
      try:
        _ = interface.fetch_crashes(test_metadata)
      except api.step.StepFailure:  # pragma: no cover
        pass

    # The autotest result object returned here is populated with the
    # "autotest_result" field instead of the "autotest_results" field.
    result = interface.parse_test_results(test_metadata)
    result.add_prejob_response(prejob_response)
    result.add_test_response(run_test_response)

    if not prejob_response.is_failure():
      dut_state = result.get_dut_state()
  finally:
    _upload_steps_with_phosphorus(api, properties, interface, result,
                                  test_metadata, dut_state, step)

  return result


def _format_time(given_time):
  """Uniformally format time into a human readable form.

  Args:
    * time (float): Float time in time.time() form.
    * step (StepPresentation): The step to add this log under.

  Return:
    string: locally formatting time in the form of (day_of_week month day
    hour:time:second year)
  """
  utctime = time.gmtime(given_time)
  return time.asctime(utctime)


def _get_context_deadline(api, limit_seconds, step):
  """Form a deadline to be used by recipe_engine/context.

  Args:
    * limit_seconds (int): Number of seconds that the process will be allowed to
      run.
    step (StepPresentation): The step to add this log under.

  Returns:
    * sections_pb2.Deadline: A luci representation of a deadline. Includes a UTC
      time and a grace period.
  """
  current_time = api.time.time()

  # Make the deadline
  deadline = sections_pb2.Deadline()
  deadline.soft_deadline = current_time + limit_seconds
  deadline.grace_period = 30.0

  # Grab the builder deadline
  builder_deadline = api.context.deadline.soft_deadline

  # Set deadline to which ever value is sooner
  deadline.soft_deadline = builder_deadline if builder_deadline < deadline.soft_deadline else deadline.soft_deadline

  step.logs[
      'result upload deadline info'] = 'start: %s\nend: %s\ntotal_seconds: %s\n' % (
          _format_time(current_time), _format_time(
              deadline.soft_deadline), str(limit_seconds))

  return deadline


def _upload_steps_with_phosphorus(api, properties, interface, result,
                                  test_metadata, dut_state, step):
  """Publish results from Phosphorus test run.

  Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
      * properties (TestRunnerProperties): recipe input properties.
      * interface (DUTInterface): The interface to run commands on the DUT.
      * result (DUTResult): results to be uploaded for later analysis.
      * test_metadata (DUTTestMetadata): All metadata needed for the interface
        to access a test.
      * upload_to_tko (bool): Flag to determine if results should be sent to
        tko.
      * step (StepPresentation): The step to add this log under.
  """
  deadline = _get_context_deadline(api, _RESULT_PUBLISHING_LIMIT, step) if (
      'chromeos.cros_infra_config.use_result_publishing_limit' in
      api.cros_infra_config.experiments or
      TestRunnerProperties.USE_RESULT_PUBLISHING_LIMIT in properties.experiments
  ) else None

  try:
    with api.context(deadline=deadline):
      try:
        try:
          archive_all_logs(api, interface=interface,
                           test_metadata=test_metadata, result=result)

          api.cts_results_archive.archive(
              interface.get_results_directory(test_metadata))
        finally:
          # We'd want to prioritize CTS artifact upload as much as possible
          # since it would be fairly expensive to rerun CTS tests if it fails
          # only on the upload step. Even though the GCS artifact upload fails,
          # the ResultDB upload will still be executed.
          _upload_to_resultdb(api, result, properties, interface, test_metadata)
      finally:
        with api.step.nest('post upload step (phosphorus)') as post_step:
          # Repair-requests need to be saved before verify the DUT.
          # Set unknown request to reset repair-requests is not needed.
          repair_requests = ['REPAIR_REQUEST_UNKNOWN']
          # Could not find cases when result is present when pre-job failed,
          # so add repair-request when result is not present or the state
          # is faillure.
          if result is not None:
            if result.prejob_response.is_failure():
              s_log(post_step, 'summary',
                    'ile-de-france: skipped as provision failed')
              repair_requests = ['REPAIR_REQUEST_PROVISION']
            else:
              dut_state = api.labpack.execute_ile_de_france(
                  common_config=properties.common_config, dut_state=dut_state)
          else:
            s_log(post_step, 'summary',
                  'ile-de-france: skipped as results is None')
            repair_requests = ['REPAIR_REQUEST_PROVISION']
          s_log(post_step, 'repair_requests', '%s' % repair_requests)
          interface.save_and_seal_skylab_local_state(dut_state, test_metadata,
                                                     repair_requests)

          publish_to_result_flow(api, properties.config,
                                 properties.request.parent_request_uid,
                                 should_poll_for_completion=True)
  # Set output properties whether or not we encounter a timeout. This is
  # required because CQ only reads results from output props and not
  # ResultsDB.
  except StepFailure as e:  # pragma: nocover
    if (e.exc_result is not None and e.exc_result.had_timeout):
      # This will make sure that the failure doesn't incorrectly present as an
      # infra_failure. We don't want to present an infra_failure because
      # nothing on our end has gone wrong and this will shield us from
      # potential misfiled bugs.
      step.presentation.staus = api.step.FAILURE
      e = StepFailure(
          'Result upload execution timelimit of %.1f hours reached' %
          (_RESULT_PUBLISHING_LIMIT / HOUR))

    # Regardless of the error we'd like to set the output properties. They
    # will likely be incomplete but since CQ relies on them anything is
    # better than empty results.
    set_output_properties(api, result=result)
    raise e
  except Exception as e:  # pragma: nocover
    # Regardless of the error we'd like to set the output properties. They
    # will likely be incomplete but since CQ relies on them anything is
    # better than empty results.
    set_output_properties(api, result=result)
    raise e

  # NOTE: It may seem chaotic since we call this in 3 different places but this
  # is done to ensure that no matter what we always upload results to
  # output_properties.
  set_output_properties(api, result=result)



def publish_to_result_flow(api, config, parent_request_uid,
                           should_poll_for_completion=False):
  """Publish build info to result_flow PubSub.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * config (Config): Input test Config.
  * parent_request_uid (string): The UID of the individual CTP request which kicked off this test run.
  * should_poll_for_completion (bool): If True, the consumers should not ACK
                                       the message until the build is complete.
  """
  with api.step.nest('publish build ID') as step:
    with api.context(infra_steps=True):
      if not api.buildbucket.build.id:
        step.step_summary_text = 'Skipped: Build ID not set'
        return
      if not config.result_flow_pubsub.topic:
        step.step_summary_text = 'Skipped: PubSub topic not set'
        return
      if not config.result_flow_pubsub.project:
        step.step_summary_text = 'Skipped: PubSub project not set'
        return
      api.result_flow.publish(
          project_id=config.result_flow_pubsub.project,
          topic_id=config.result_flow_pubsub.topic, build_type='test_runner',
          should_poll_for_completion=should_poll_for_completion,
          parent_uid=parent_request_uid)


def execution_steps_with_phosphorus(api, properties):
  """Runs all the non-UI-related steps.

  Runs all tests specified in properties, saving relevant data, and returning
  the overall results.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * properties (TestRunnerProperties): recipe input properties.

  Returns: DUTResult: The result for all tests run in this run.

  Raises:
  * InfraFailure.
  """
  interface = api.dut_interface.create(api, properties)
  tests = _collect_tests_for_phosphorus(properties.request)
  global_result = interface.build_empty_result()

  with api.step.nest('inputs') as step:
    s_log(step, 'request', json_format.MessageToJson(properties.request))
    s_log(step, 'config', json_format.MessageToJson(properties.config))
    s_log(step, 'common_config',
          json_format.MessageToJson(properties.common_config))
    # Use parent_build_id rather than the related parent_buildbucket_id tag,
    # since that doesn't seem to work here. https://crbug.com/1171511
    if properties.request.parent_build_id:
      s_link(
          step=step, name='parent CTP', link=api.buildbucket.build_url(
              build_id=properties.request.parent_build_id))

  with api.step.nest('execution steps') as step:
    publish_to_result_flow(api, properties.config,
                           properties.request.parent_request_uid)

    for test_id, test in tests.items():
      with api.step.nest(test_id) as test_step:
        validate_request(api, test)
        if 'build' in test.autotest.keyvals and test.autotest.keyvals[
            'build'].startswith('betty'):
          raise api.step.StepFailure('VMTest should go through CFT.')
        test_metadata = interface.build_test_metadata(test_id, test)
        # Needs to be distinct per test as logs are uploaded for each test separately.
        repair_requests = ['REPAIR_REQUEST_PROVISION']
        interface.save_skylab_local_state(_DUT_STATE_NEEDS_REPAIR,
                                          test_metadata,
                                          repair_requests=repair_requests)

        dut_state = _DUT_STATE_NEEDS_REPAIR
        max_duration_sec = int(
            properties.config.harness.prejob_deadline_seconds or
            _PROVISION_DEADLINE)

        # Allow users to set custom provision deadline so long as it is greater
        # or less than the maximum allowed.
        max_duration_sec = min(max_duration_sec, _PROVISION_DEADLINE)

        if interface.is_within_deadline():
          result = _execution_steps_for_test_with_phosphorus(
              api=api,
              properties=properties,
              interface=interface,
              test_metadata=test_metadata,
              max_duration_sec=max_duration_sec,
              dut_state=dut_state,
              container_image_info=properties.request.execution_param
              .container_image_info,
              step=test_step,
          )

          global_result.add_result(test_id, result)
        else:
          prejob_response = interface.build_aborted_prejob_response(
              test_metadata)
          result = interface.parse_test_results(test_metadata)
          result.add_prejob_response(prejob_response)
          global_result.add_result(test_id, result)
          archive_all_logs(api, interface=interface,
                           test_metadata=test_metadata, result=result)

    interface.remove_autotest_results_dir()

  return global_result

  ###################### CTR related functions ###################################


def execution_steps_with_ctr(api, properties):
  """Runs all the non-UI-related steps using ctr.

  Runs all tests specified in properties, saving relevant data, and returning
  the overall results.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * properties (TestRunnerProperties): recipe input properties.

  Returns: DUTResult: The result for all tests run in this run.

  Raises:
  * InfraFailure.
  """
  interface = api.dut_interface.create(api, properties)
  global_result = interface.build_empty_result()

  with api.step.nest('inputs') as step:
    s_log(step, 'cft_test_request',
          json_format.MessageToJson(properties.cft_test_request))
    if properties.cft_test_request.parent_build_id:
      s_link(
          step=step, name='parent CTP', link=api.buildbucket.build_url(
              build_id=properties.cft_test_request.parent_build_id))

  with api.step.nest('inputs validation') as step:
    _validate_inputs_for_ctr(api, properties)

  with api.step.nest('execution steps') as step:
    # create the container images file
    # that will be used later by CTR commands.
    with api.step.nest('CrosToolRunner: create images file'):
      api.cros_tool_runner.create_file_with_container_metadata(
          properties.cft_test_request.container_metadata)
    publish_to_result_flow(api, properties.config,
                           properties.cft_test_request.parent_request_uid)
    test_metadata = interface.build_test_metadata(
        'original_test', '', properties.cft_test_request.autotest_keyvals,
        properties.cft_test_request)

    repair_requests = ['REPAIR_REQUEST_PROVISION']
    interface.save_skylab_local_state(_DUT_STATE_NEEDS_REPAIR, test_metadata,
                                      repair_requests=repair_requests)

    dut_state = _DUT_STATE_NEEDS_REPAIR
    max_duration_sec = int(properties.config.harness.prejob_deadline_seconds or
                           _PROVISION_DEADLINE)

    # Allow users to set custom provision deadline so long as it is greater
    # or less than the maximum allowed.
    max_duration_sec = min(max_duration_sec, _PROVISION_DEADLINE)

    if interface.is_within_deadline():
      result = _execution_steps_for_test_with_ctr(
          api=api, properties=properties, interface=interface,
          test_metadata=test_metadata, max_duration_sec=max_duration_sec,
          dut_state=dut_state, container_image_info=None, step=step)

      global_result.add_result('original_test', result)
    else:
      prejob_response = interface.build_aborted_prejob_response(test_metadata)
      result = interface.parse_test_results(test_metadata)
      result.add_prejob_response(prejob_response)
      global_result.add_result('original_test', result)

  return global_result


def _execution_steps_for_test_with_ctr(api, properties, interface,
                                       test_metadata, max_duration_sec,
                                       dut_state, container_image_info, step):
  """Execute all the required steps for a single test using ctr.

  Run the following steps required for a test:
      * Run provision (prepare machine)
      * Run test

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * properties (TestRunnerProperties): recipe input properties.
  * interface (DUTInterface): The interface to run commands on the DUT.
  * test_metadata (DUTTestMetadata): All metadata needed for the interface
        to access a test.
  * max_duration_sec (int): Maximum amount of time the job should run.
  * dut_state (str): The current state of the DUT.
  * container_image_info (ContainerImageInfo): If set, info on a Docker
  container for use by the DUTInterface.
  * step (StepPresentation): The step to add this log under.

  Returns: DUTResult: a constructed result for this test.

  Raises:
  * InfraFailure.
  """
  result_for_uploading = None
  result_for_output_props = None
  run_test_response = None
  run_test_resp_for_output_props = None
  results_dir = ''

  try:
    prejob_response = interface.submit_pre_job(test_metadata, max_duration_sec)
    if not prejob_response.any_provision_failed:
      run_test_response = interface.run_test(test_metadata,
                                             container_image_info)
      run_test_resp_for_output_props, run_test_response = interface.process_test_responses(
          run_test_response)
      test_metadata.job_finished = int(api.time.time())
      dut_state = _DUT_STATE_READY

      # Gets the result dir path for the first test case result,
      # e.g. "/home/chromeos-test/skylab_bots/c6-r1-r24-h11.584871424/w/ir/x/w
      #  /recipe_cleanup/output_dirWVny4f
      #  /cros-test/artifact/tauto
      #  /results-1-bluetooth_AdapterAdvHealth.adv_reboot_advertising_test"
      if len(run_test_response.test_dut_responses) > 0:
        ctr_test_response = run_test_response.test_dut_responses[0].data
        results_dir = ctr_test_response.result_dir_path.path

      # Skips reading the log files when the result_dir_path is empty. When
      # test/harness crashes, result_dir_path will be empty
      sysinfo_keyvals = {}
      autotest_keyval_file = {}
      if results_dir:
        sysinfo_file_paths = [os.path.join(results_dir, 'sysinfo')]
        sysinfo_keyvals = _read_sysinfo_keyvals(api, sysinfo_file_paths)
        autotest_keyval_path = os.path.join(results_dir, 'keyval')
        autotest_keyval_file = _read_autotest_keyval_file(
            api, autotest_keyval_path)
      autotest_keyval_file.update(test_metadata.autotest_keyvals)

      try:
        test_metadata.rdb_sources_file = _prepare_resultdb_sources_file(
            api, properties)
      except SourcesNotAvailableException:  # pragma: nocover
        pass
      test_metadata.rdb_base_tags = _generate_resultdb_base_tags(
          api, properties, test_metadata, autotest_keyval_file, sysinfo_keyvals,
          cft_is_enabled=True)
      test_metadata.rdb_base_variant = _generate_resultdb_variant_def(
          api, autotest_keyval_file)

    # Result for uploading
    result_for_uploading = interface.parse_test_results(test_metadata)
    result_for_uploading.add_prejob_response(prejob_response)
    result_for_uploading.add_test_response(run_test_response)

    # Result for output props
    result_for_output_props = interface.parse_test_results(test_metadata)
    result_for_output_props.add_prejob_response(prejob_response)
    result_for_output_props.add_test_response(run_test_resp_for_output_props)
    result_for_output_props.update_log_urls(test_metadata)
  finally:
    if (result_for_uploading is not None and result_for_uploading.is_failure()
       ) or (result_for_output_props is not None and
             result_for_output_props.is_failure()):
      dut_state = _DUT_STATE_NEEDS_REPAIR
    _upload_steps_with_ctr(api, properties, interface, result_for_output_props,
                           result_for_uploading, results_dir, test_metadata,
                           dut_state, step)

  return result_for_output_props

def _upload_steps_with_ctr(api, properties, interface, result_for_output_props,
                           result_for_uploading, results_dir, test_metadata,
                           dut_state, step):
  """Publish results from Phosphorus test run.

  Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * properties (TestRunnerProperties): Recipe input properties.
    * interface (DUTInterface): The interface to run commands on the DUT.
    * result_for_output_props (DUTResult): Results to be sent to bq output
      properties.
    * result_for_uploading (DUTResult): Results to be uploaded for later
      analysis.
    * run_test_response (CrosToolRunnerTestDUTResponse): Response from the test
      execution, specifically in the phosphorus environment.
    * results_dir (str): Local(to bot) path where results are stored.
    * test_metadata (DUTTestMetadata): All metadata needed for the interface
        to access a test.
    * dut_state (str): The current state of the DUT.
    * step (StepPresentation): The step to add this log under.
  """
  # If the experiment is set then form a deadline.
  deadline = _get_context_deadline(api, _RESULT_PUBLISHING_LIMIT, step) if (
      'chromeos.cros_infra_config.use_result_publishing_limit' in
      api.cros_infra_config.experiments or
      TestRunnerProperties.USE_RESULT_PUBLISHING_LIMIT in properties.experiments
  ) else None

  def _prep_and_set_output_props():
    """Inline function to allow us to set output props.
    """
    # Get an empty result for setting output property
    # result.data is not used anywhere else so
    # it's okay to create an empty one for only this purpose
    new_result = interface.parse_test_results(test_metadata)
    new_result.data = create_skylab_result(api, result_for_output_props,
                                           properties, dut_state)
    set_output_properties(api, result=new_result)

  # Upload results with context
  try:
    with api.context(deadline=deadline):
      try:
        if (result_for_uploading is not None and
            not result_for_uploading.prejob_response.any_provision_failed):
          # TODO(b/246473902): Populate additional info to Tauto results for CFT
          # MVP, e.g. timestamps, full test name. The logic would be added to
          # crostoolrunner_interface.py and could be similar to the
          # `_post_process_tauto_result()` method above.

          skip_board_model_check = properties.common_config.skip_board_model_realm_check
          visibility_mode = properties.results_upload_config.mode
          custom_realm = properties.common_config.rdb_config.custom_realm_name

          interface.upload_to_rdb(test_metadata,
                                  result_for_uploading.test_responses,
                                  skip_board_model_check, visibility_mode,
                                  custom_realm)
      finally:
        with api.step.nest('post upload step (ctr)') as post_step:
          interface.submit_post_job()
          provision_failed = result_for_output_props is not None and result_for_output_props.prejob_failed(
          )
          repair_requests = ['REPAIR_REQUEST_UNKNOWN']
          if provision_failed:
            failure_reason = result_for_output_props.prejob_response.failure_reason
            # List of the reason when no repair-request is required.
            ok_reasons = [
                'REASON_INVALID_REQUEST', 'REASON_GS_UPLOAD_FAILED'
            ]
            if failure_reason not in ok_reasons:
              repair_requests = ['REPAIR_REQUEST_PROVISION']
          s_log(post_step, 'repair_request', '%s' % repair_requests)
          interface.save_and_seal_skylab_local_state(
              dut_state, test_metadata, repair_requests=repair_requests)

          archive_all_logs(api, interface=interface,
                           test_metadata=test_metadata,
                           result=result_for_uploading)
          # TODO(b/252945582): Handle multiple test results if needed
          if results_dir:
            # The existing code expects $dir/*/cheets_?TS*/results/ to contain CTS
            # results. To align with that, we need to pass the directory
            # .../cros-test/artifacts/tauto/, not its sub directory.
            api.cts_results_archive.archive(os.path.dirname(results_dir))
          if provision_failed:
            s_log(post_step, 'ile-de-france', 'running')
            dut_state = api.labpack.execute_ile_de_france(
                common_config=properties.common_config, dut_state=dut_state)
            interface.save_and_seal_skylab_local_state(dut_state, test_metadata)
          else:
            s_log(post_step, 'ile-de-france', 'intentionally skipped')

          publish_to_result_flow(api, properties.config,
                                 properties.cft_test_request.parent_request_uid,
                                 should_poll_for_completion=True)
    # Set output properties whether or not we encounter a timeout. This is
    # required because CQ only reads results from output props and not
    # ResultsDB.
  except StepFailure as e:  # pragma: nocover
    if (e.exc_result is not None and e.exc_result.had_timeout):
      # This will make sure that the failure doesn't incorrectly present as an
      # infra_failure. We don't want to present an infra_failure because
      # nothing on our end has gone wrong and this will shield us from
      # potential misfiled bugs.
      step.presentation.staus = api.step.FAILURE
      e = StepFailure(
          'Result upload execution timelimit of %.1f hours reached' %
          (_RESULT_PUBLISHING_LIMIT / HOUR))

    # Regardless of the error we'd like to set the output properties. They
    # will likely be incomplete but since CQ relies on them anything is
    # better than empty results.
    _prep_and_set_output_props()
    raise e
  except Exception as e:  # pragma: nocover
    _prep_and_set_output_props()
    raise e

  # NOTE: It may seem chaotic since we call this in 3 different places but this
  # is done to ensure that no matter what we always upload results to
  # output_properties.
  _prep_and_set_output_props()


def create_skylab_result(api, ctr_result, properties, dut_state):
  """Create skylab_result from ctr_result.

    Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
      * ctr_result (DUTResult): The result of all tests.
      * properties (TestRunnerProperties): recipe input properties.
      * dut_state (str): State of the dut that should be set.

    Returns: Skylab_result: Skylab_result for current test.
    """
  with api.step.nest('create skylab result') as step:
    # Even though test_runner(for CFT workflow) itself supports multiple suites/test-cases together,
    # CTPV1 does not. So there should be always one test-case in one suite.
    test_suite = properties.cft_test_request.test_suites[0]
    test_names = [test.value for test in test_suite.test_case_ids.test_case_ids]

    # Default values
    prejob_verdict = Result.Prejob.Step.VERDICT_FAIL
    prejob_reason = ''
    is_incomplete = True
    test_verdict = Result.Autotest.TestCase.VERDICT_NO_VERDICT
    log_data = TaskLogData()
    test_cases = []

    # Parsing required only when prejob is successful
    if ctr_result and ctr_result.prejob_response and not ctr_result.prejob_response.any_provision_failed:
      # Parse prejob result
      prejob_verdict = Result.Prejob.Step.VERDICT_PASS
      # Parse test results
      if ctr_result.test_responses:
        is_incomplete = False
        for resp in ctr_result.test_responses:
          if resp.is_failure():
            test_verdict = Result.Autotest.TestCase.VERDICT_FAIL
          else:
            test_verdict = Result.Autotest.TestCase.VERDICT_PASS
          test_cases.append(
              Result.Autotest.TestCase(
                  name=resp.data.test_case_id.value, verdict=test_verdict,
                  human_readable_summary=_get_failure_reason_from_test_result(
                      resp)))
      # Parse log data
      if ctr_result.gs_url:
        log_data.gs_url = ctr_result.gs_url
      if ctr_result.testhaus_url:
        log_data.testhaus_url = ctr_result.testhaus_url

    if not test_cases:
      # if prejob failed, add the test cases
      test_cases = [
          Result.Autotest.TestCase(name=test_name, verdict=test_verdict)
          for test_name in test_names
      ]
      prejob_reason = _get_prejob_failure_reason_from_ctr_results(ctr_result)

    autotest_result = Result.Autotest(test_cases=test_cases,
                                      incomplete=is_incomplete)

    skylab_result = Result(
        prejob=Result.Prejob(step=[
            Result.Prejob.Step(name='provision', verdict=prejob_verdict,
                               human_readable_summary=prejob_reason)
        ]), autotest_result=autotest_result,
        autotest_results={'original_test': autotest_result},
        state_update=Result.StateUpdate(dut_state=dut_state), log_data=log_data)
    s_log(step, 'skylab_result', json_format.MessageToJson(skylab_result))
    return skylab_result


def summarize_results_from_ctr_results(api, result):
  """Display test cases (and failures) as recipe substeps through the api.

    Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
      * result (DUTResult): The result of all tests.
    """
  with api.step.nest('Results') as step:
    # Do not surface empty link when provision has failure
    if not result.prejob_failed():
      if result.get_testhaus_log_url():
        s_link(step=step, name='Logs in Testhaus',
               link=result.get_testhaus_log_url())
    for pre_job in result.get_prejob_steps():
      _set_step_status(api=api, step_name='provision of ' + pre_job.test_id,
                       summary='', failure_condition=pre_job.is_failure())
    for test_result in result.get_test_results():
      if test_result.is_skipped():
        continue
      _set_step_status(api=api, step_name=test_result.test_id, summary='',
                       failure_condition=test_result.is_failure())


def _validate_inputs_for_ctr(api, properties):
  """Validate inputs for CTR.

    Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
      * properties (TestRunnerProperties): recipe input properties.
    """
  _validate_proto_field(api, properties, 'cft_test_request', True)
  _validate_proto_field(api, properties.cft_test_request, 'primary_dut', True)
  _validate_proto_field(api, properties.cft_test_request, 'container_metadata',
                        True)
  _set_step_status(
      api=api, step_name='container_metadata_key validation',
      summary='container_metadata_key is missing',
      failure_condition=not properties.cft_test_request.primary_dut
      .container_metadata_key, fail_build=True)
  _set_step_status(
      api=api, step_name='test_suites validation',
      summary='test_suites is missing',
      failure_condition=not properties.cft_test_request.test_suites,
      fail_build=True)


def _get_prejob_failure_reason_from_ctr_results(ctr_result):
  """Return prejob reason from ctr result if any.

    Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
      * ctr_result (DUTResult): The result of all tests.
    """
  if not ctr_result:
    return ''  # pragma: nocover
  if not ctr_result.prejob_response:
    return ''  # pragma: nocover
  if not ctr_result.prejob_response.prejob_dut_responses:
    return ''  # pragma: nocover
  if not ctr_result.prejob_response.prejob_dut_responses[0].data:
    return ''  # pragma: nocover
  if not ctr_result.prejob_response.prejob_dut_responses[0].data.failure:
    return ''  # pragma: nocover

  return ctr_api.provision_service.InstallFailure.Reason.Name(
      ctr_result.prejob_response.prejob_dut_responses[0].data.failure.reason)


def _get_failure_reason_from_test_result(test_result):
  """Return failure reason from ctr test result if any.

    Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
      * test_result (CrosToolRunnerTestDUTResponse): The result of a single test.
    """

  if not test_result:
    return ''  # pragma: nocover
  if not test_result.data:
    return ''  # pragma: nocover
  if not test_result.data.reason:
    return ''  # pragma: nocover

  return test_result.data.reason


def _trv2_post_processing(api):
  """Post process test runner v2 results: locate test result directory and send
    to CTS archiver.
    Example of test result directory (with TRv2 & cros-tool-runner v2):
    - On GCE bot: /b/s/w/ir/x/w
                  /recipe_cleanup/tmphizmnig2/cros-test-9n2da52a
                  /cros-test/results/tauto
    - On Drone bot: /home/chromeos-test/skylab_bots/f-v-d13.1401099833/w/ir/x/w
                    /recipe_cleanup/output_dirwbzlcct1/cros-test-bf71b245
                    /cros-test/results/tauto
    Note that CWR a.k.a. api.path.start_dir is isolated for each build.
    Random directory is created e.g. `recipe_cleanup/*`.
    TRv2 creates a unique folder for each docker container e.g. `cros-test-*`
    We simply use `**` to match any of those randomly named folders and rely on
    the pattern `cros-test/results/tauto` to identify the test result directory.
    (cros-test/results is defined in cros-tool-runner v2 cros-test template)

    Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
    """
  with api.step.nest('Post processing test results') as step:  # pragma: nocover
    dirs = api.file.glob_paths(
        'List test results directories for CTS archiver', api.path.start_dir,
        os.path.join('**', 'cros-test', 'results', 'tauto'))
    if len(dirs) == 0:
      s_log(step, 'Skip processing', 'No directories found, skip CTS archiving')
      step.presentation.step_summary_text = 'Skipped: no test directory found'
      return
    for directory in dirs:
      api.cts_results_archive.archive(str(directory))


def raise_on_trv2_result(api, res):  # pragma: nocover
  """Decompress trv2 result and raise StepFailure on prejob or test failure.

  Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * res - The step result.
  """
  if 'compressed_result' in res.step.sub_build.output.properties:
    compressed_result = res.step.sub_build.output.properties[
        'compressed_result']
    decompressed_result = zlib.decompress(base64.b64decode(compressed_result))
    result = Result()
    result.ParseFromString(decompressed_result)
    if result.prejob:
      for s in result.prejob.step:
        if s.verdict != Result.Prejob.Step.VERDICT_PASS:
          raise api.step.StepFailure('prejob %s failed: %s' %
                                     (s.name, s.human_readable_summary))

    # Collect test failures by verdict for better step failure text
    failed_tests = {}
    if result.autotest_result:
      for test_case in result.autotest_result.test_cases:
        if test_case.verdict in [
            Result.Autotest.TestCase.VERDICT_PASS,
        ]:
          continue
        if test_case.verdict not in failed_tests:
          failed_tests[test_case.verdict] = []
        failed_tests[test_case.verdict].append(test_case)

    # TODO(cdelagarza): Format test failures grouped by verdicts.
    if failed_tests:
      raise api.step.StepFailure('test failed')

  if 'errorSummaryMarkdown' in res.step.sub_build.output.properties:
    error_summary = res.step.sub_build.output.properties['errorSummaryMarkdown']
    if error_summary:
      raise api.step.StepFailure(error_summary)


def run_and_upload(api, properties):
  """Run test and upload results.

  Args:
    api: a RecipeScriptApi instance
    properties: a TestRunnerProperties instance

  Returns:
    None
  """
  api.easy.log_parent_step()
  # Set max_threads to 1 for whole test_runner build. Details: b/270152591.
  api.cipd.max_threads = 1

  if properties.cft_is_enabled and api.cros_test_runner.is_enabled() and (
      api.cros_test_runner.is_dynamic() or
      properties.cft_test_request.run_via_trv2):  # pragma: nocover
    try:
      # Use cros_test_runner binary rather than the normal test_runner workflow.
      result = api.cros_test_runner.execute_luciexe()
      raise_on_trv2_result(api, result)
    finally:
      _trv2_post_processing(api)
    return
  if properties.cft_is_enabled:
    result = execution_steps_with_ctr(api, properties)
    summarize_results_from_ctr_results(api, result)
  else:
    result = execution_steps_with_phosphorus(api, properties)
    # The labapck code path is relatively new and not on the critical path for test_runner.py yet.
    # Exceptions should NOT be allowed to propagate out of the next block and cause the test to fail.
    try:
      # Ensure the existence of labpack, but don't do anything else.
      # The only thing that this does is download a CIPD package.
      _ = api.labpack.ensure_labpack()
    except Exception:  # pragma: nocover #pylint: disable=broad-except
      pass
    summarize_results_from_phosphorus_results(api, result)

  if result.has_any_failures():
    with api.step.nest('build status'):
      if result.test_failed():
        raise api.step.StepFailure('test failed')
      if result.prejob_failed():
        raise api.step.StepFailure('prejob failed')
      raise api.step.StepFailure('prejob or test failed')


def RunSteps(api, properties):
  """Entrypoint to the script

  Args:
    api: a RecipeScriptApi instance
    properties: a TestRunnerProperties instance

  Returns:
    None
  """
  try:
    run_and_upload(api, properties)
  finally:
    pass


def GenTests(api):

  def _set_build(bid, tags=None, experiments=None, swarming_tags=None,
                 swarming_task_dimensions=None, ancestor_buildbucket_ids=None):
    # parent_task_id is needed by cts_results_archive step. In reality it's
    # always present unless run via led.
    tags = tags or {}
    tags['parent_task_id'] = tags.get('parent_task_id', 'parent-task-id1')

    # tags is a dict, convert that into [StringPair].
    bb_tags = api.cros_tags.tags(**tags)
    build_msg = api.buildbucket.ci_build_message(
        build_id=bid, tags=bb_tags, experiments=experiments, project='chromeos',
        bucket='test_runner', builder='test_runner', on_backend=True)
    build_msg.infra.backend.task.id.target = 'swarming://chromeos'
    if swarming_tags:
      build_msg = api.buildbucket.extend_swarming_bot_dimensions(
          build_msg, swarming_tags)
    if swarming_task_dimensions:
      build_msg.infra.backend.task_dimensions.extend(swarming_task_dimensions)
    build_msg.infra.swarming.parent_run_id = 'parent-task-id1'

    if ancestor_buildbucket_ids:
      build_msg.ancestor_ids.extend(ancestor_buildbucket_ids)
    return api.buildbucket.build(build_msg)

  def _build_with_execution_timeout(timeout_s):
    # NB: The input Build does not have start_time set, because buildbucket has
    # no way of knowing when the swarming task for the build will start.
    return build_pb2.Build(
        id=22,
        execution_timeout=duration_pb2.Duration(seconds=timeout_s),
    )

  def _mock_autotest_wrapper_tast_result():
    return api.step_data(
        'execution steps.original_test.Phosphorus: get test results.'
        'call `phosphorus`.parse',
        stdout=api.raw_io.output(
            json_format.MessageToJson(
                Result(
                    autotest_result=Result.Autotest(test_cases=[
                        Result.Autotest.TestCase(
                            # The autotest wrapper tast result is named
                            # "tast".
                            name='tast',
                            verdict=Result.Autotest.TestCase.VERDICT_PASS),
                    ]),
                ))))

  def _autotest_keyval_file_step_data():
    return api.step_data(
        'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
        '.read autotest keyval file',
        api.file.read_text('''
parent_job_id=58067d9ab42aca11
build=board-cq/R00-0.0.0
suite=sweet-cq
synchronous_log_data_testhaus_url=https://path/to/testhaus
synchronous_log_data_url=gs://path/to/test/logs
branch=main
label=board-cq/R00-0.0.0/sweet-cq/test-case
build_config=eve-release
master_build_config=master-release
build_target=target
ash_version=109.0.5391.0
lacros_version=109.0.5391.0
drone=skylab-drone-xyz
hostname=chromeos0-row0-rack0-host0
job_started=1651467359
status_version=0
user=test-user
job_finished=1651468010
tast_missing_test.0=foo.SomeTest
tast_missing_test.1=foo.SomeOtherTest
tast_missing_test.2=bar.DifferentTest
tast_missing_test.3=bar.YetAnotherTest
    '''))

  def _autotest_keyval_file_step_data_no_timestamps():
    return api.step_data(
        'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
        '.read autotest keyval file',
        api.file.read_text('''
parent_job_id=58067d9ab42aca11
build=board-cq/R00-0.0.0
suite=sweet-cq
synchronous_log_data_testhaus_url=https://path/to/testhaus
synchronous_log_data_url=gs://path/to/test/logs
branch=main
label=board-cq/R00-0.0.0/sweet-cq/test-case
build_config=eve-release
master_build_config=master-release
drone=skylab-drone-xyz
hostname=chromeos0-row0-rack0-host0
status_version=0
user=test-user
tast_missing_test.0=foo.SomeTest
tast_missing_test.1=foo.SomeOtherTest
tast_missing_test.2=bar.DifferentTest
tast_missing_test.3=bar.YetAnotherTest
    '''))

  def _crossystem_keyval_file_step_data():
    return api.step_data(
        'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
        '.read crossystem keyval file',
        api.file.read_text('''
fw_prev_result          = success                        # [RO/str] Firmware result of previous boot
fw_prev_tried           = B                              # [RO/str] Firmware tried on previous boot (A or B)
fw_result               = success                        # [RW/str] Firmware result this boot
fw_tried                = B                              # [RO/str] Firmware tried this boot (A or B)
fw_try_count            = 0                              # [RW/int] Number of times to try fw_try_next
fw_try_next             = B                              # [RW/str] Firmware to try next (A or B)
fw_vboot2               = 1                              # [RO/int] 1 if firmware was selected by vboot2 or 0 otherwise
fwb_tries               = 0                              # [RW/int] Try firmware B count
fwid                    = Google_Voema.13672.224.0       # [RO/str] Active firmware ID
fwupdate_tries          = 0                              # [RW/int] Times to try OS firmware update (inside kern_nv)
hwid                    = VOEMA-DHAS C4B-D3A-C3C-37Y-A83 # [RO/str] Hardware ID
ro_fwid                 = Google_Voema.13672.224.0       # [RO/str] Read-only firmware ID
    '''))

  def _gsctool_keyval_file_step_data():
    return api.step_data(
        'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
        '.read gsctool keyval file',
        api.file.read_text('''
start
target running protocol version 6
keyids: RO 0xc7d40497, RW 0xfba25ca9
offsets: backup RO at 0, backup RW at 0x4000
Current versions:
RO 0.0.38
RW 0.24.13
    '''))

  def _servo_keyval_file_step_data():
    return api.step_data(
        'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
        '.read servo keyval file',
        api.file.read_text('''
ccd_cr50_version.ccd_flex_secondary=0.6.190/cr50_v3.94_pp.192-3677cf40af
servo_host_os_version=fizz-labstation-release/R114-15437.59.0
servo_micro_version.main=servo_micro_v2.4.73-d771c18ba9
servo_type=servo_v4_with_servo_micro_and_ccd_cr50
servo_v4_version.root=servo_v4_v2.4.58-c37246f9c
servod_version=v1.0.1732-67007a28 2023-06-20 19:22:43
    '''))

  def _kernel_log_file_step_data():
    return api.step_data(
        'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
        '.read kernel log file',
        api.file.read_text('''
Linux localhost 5.4.190-18482-g9cffa68a11c1 #1 SMP PREEMPT Wed Apr 27 18:24:08 PDT 2022 x86_64 Intel(R) Core(TM) i7-7Y75 CPU @ 1.30GHz GenuineIntel GNU/Linux
  '''))

  def _tast_test_result_file_step_data():
    return api.step_data(
        'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
        '.read test results from streamed_results.jsonl',
        api.file.read_text('''
{
   "name":"crostini.SSHFSMount.bullseye_stable",
   "pkg":"chromiumos/tast/local/bundles/cros/crostini",
   "desc":"Checks crostini SSHFS mount",
   "contacts":[
      "clumptini+oncall@google.com"
   ],
   "attr":[
      "group:mainline",
      "name:crostini.SSHFSMount.bullseye_stable",
      "bundle:cros",
      "dep:chrome",
      "dep:vm_host",
      "dep:dlc"
   ],
   "data":null,
   "softwareDeps":[
      "chrome",
      "vm_host",
      "dlc"
   ],
   "fixture":"crostiniBullseye",
   "timeout":420000000000,
   "bundle":"cros",
   "errors":null,
   "start":"2022-09-02T03:54:14.032069253Z",
   "end":"2022-09-02T03:54:15.173194233Z",
   "outDir":"/usr/local/autotest/results/lxc_job_folder/tast/results/tests/crostini.SSHFSMount.bullseye_stable",
   "skipReason":""
}
    '''))

  def _tauto_test_result_file_step_data():
    return api.step_data(
        'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
        '.read test results from test_runner_result.json',
        api.file.read_text('''
{
  "autotest_result": {
    "test_cases": [
      {
        "name": "login_LoginSuccess",
        "verdict": "VERDICT_PASS"
      }
    ]
  },
  "log_data": {
    "gs_url": "gs://chromeos-test-logs/test-runner/prod/2022-09-02/fbfd7251-279f-4fc9-9613-e7e03e365a47",
    "testhaus_url": "https://tests.chromeos.goog/p/chromeos/logs/unified/chromeos-test-logs/test-runner/prod/2022-09-02/fbfd7251-279f-4fc9-9613-e7e03e365a47"
  },
  "prejob": {
    "step": [
      {
        "name": "provision",
        "verdict": "VERDICT_PASS"
      }
    ]
  },
  "state_update": {
    "dut_state": "ready"
  }
}
    '''))

  def _autotest_wrapper_tast_result_file_step_data():
    return api.step_data(
        'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
        '.read test results from autotest_wrapper_tast_result.json',
        api.file.read_text('''
{
  "autotest_result": {
    "test_cases": [
      {
        "name": "tast.critical-system-shard-2",
        "verdict": "VERDICT_PASS"
      }
    ]
  },
  "log_data": {
    "gs_url": "gs://chromeos-test-logs/test-runner/prod/2022-09-02/fbfd7251-279f-4fc9-9613-e7e03e365a47",
    "testhaus_url": "https://tests.chromeos.goog/p/chromeos/logs/unified/chromeos-test-logs/test-runner/prod/2022-09-02/fbfd7251-279f-4fc9-9613-e7e03e365a47"
  },
  "prejob": {
    "step": [
      {
        "name": "provision",
        "verdict": "VERDICT_PASS"
      }
    ]
  },
  "state_update": {
    "dut_state": "ready"
  }
}
    '''))

  # Required for initial module set up.
  def _misc_properties(cft_is_enabled=False, use_result_publishing_limit=False,
                       non_compliant_prejob_deadline=False):
    if cft_is_enabled:
      return _misc_properties_for_ctr(
          use_result_publishing_limit=use_result_publishing_limit,
          non_compliant_prejob_deadline=non_compliant_prejob_deadline)
    return _misc_properties_for_phosphorus(
        use_result_publishing_limit=use_result_publishing_limit,
        non_compliant_prejob_deadline=non_compliant_prejob_deadline)

  def _misc_properties_for_ctr(use_result_publishing_limit=False,
                               non_compliant_prejob_deadline=False):
    return (api.properties(
        _get_test_runner_properties(
            use_result_publishing_limit=use_result_publishing_limit,
            non_compliant_prejob_deadline=non_compliant_prejob_deadline), **{
                '$chromeos/phosphorus':
                    PhosphorusProperties(
                        version=PhosphorusProperties.Version(
                            cipd_label='phosphorus_prod'), config={
                                'admin_service': 'foo-service',
                                'cros_inventory_service': 'inv-service',
                                'cros_ufs_service': 'ufs-service',
                                'autotest_dir': '/path/to/autotest',
                            }),
                '$chromeos/cros_tool_runner':
                    CrosToolRunnerProperties(
                        version=CrosToolRunnerProperties.Version(
                            cipd_label='cros_tool_runner_prod'))
            }) + api.properties.environ(
                PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                        SWARMING_TASK_ID='dummy-task-id1',
                                        SKYLAB_DUT_ID='dummy-dut-id')) +
            api.properties.environ(
                CrosToolRunnerEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                            SWARMING_TASK_ID='dummy-task-id1',
                                            SKYLAB_DUT_ID='dummy-dut-id')))

  def _get_test_runner_properties(use_result_publishing_limit=False,
                                  non_compliant_prejob_deadline=False):
    experiments = []
    if use_result_publishing_limit:
      experiments.append(TestRunnerProperties.USE_RESULT_PUBLISHING_LIMIT)

    prejob_deadline = HOUR
    if non_compliant_prejob_deadline:
      prejob_deadline = _24_HOURS
    return TestRunnerProperties(
        config={
            'lab': {
                'admin_service': 'foo-service',
                'cros_inventory_service': 'inv-service',
                'cros_ufs_service': 'ufs-service'
            },
            'harness': {
                'autotest_dir': '/path/to/autotest',
                'prejob_deadline_seconds': prejob_deadline,
            },
            'output': {
                'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
            },
            'result_flow_pubsub': {
                'project': 'foo-proj',
                'topic': 'foo-topic',
            },
        }, experiments=experiments)

  def _misc_properties_for_phosphorus(use_result_publishing_limit=False,
                                      non_compliant_prejob_deadline=False):
    return (api.properties(
        _get_test_runner_properties(
            use_result_publishing_limit=use_result_publishing_limit,
            non_compliant_prejob_deadline=non_compliant_prejob_deadline), **{
                '$chromeos/phosphorus':
                    PhosphorusProperties(
                        version=PhosphorusProperties.Version(
                            cipd_label='phosphorus_prod'), config={
                                'admin_service': 'foo-service',
                                'cros_inventory_service': 'inv-service',
                                'cros_ufs_service': 'ufs-service',
                                'autotest_dir': '/path/to/autotest',
                            })
            }) + api.properties.environ(
                PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                        SWARMING_TASK_ID='dummy-task-id1',
                                        SKYLAB_DUT_ID='dummy-dut-id')))

  # An example request.
  def _request_properties():
    return (api.properties(
        TestRunnerProperties(request=_canned_test_runner_request())))

  def _request_properties_no_name():
    return (api.properties(
        TestRunnerProperties(request=_canned_request_missing_name())))

  # An example request with multiple tests on the test field.
  def _request_properties_multitest():
    return (api.properties(
        TestRunnerProperties(request=_canned_multitest_request())))

  # An example request with multiple duts requested in prejob field.
  def _request_properties_multiduts():
    return (api.properties(
        TestRunnerProperties(request=_canned_milti_duts_request())))

  # An example request with multiple duts(with android devices)
  # requested in prejob field.
  def _request_properties_multiduts_with_androids():
    return (api.properties(
        TestRunnerProperties(
            request=_canned_milti_duts_with_android_request())))

  # An example request represents chromium tests which upload result
  # to rdb.
  def _request_properties_rdb(test_arg):
    return (api.properties(
        TestRunnerProperties(request=_canned_test_runner_request(test_arg))))

  # An example request with a default TestExecutionBehavior specified.
  def _request_properties_with_test_exec_behavior(default_behavior,
                                                  test_name='tauto'):
    return (api.properties(
        TestRunnerProperties(
            request=_canned_test_runner_request(
                default_behavior=default_behavior, test_name=test_name))))

  def _request_properties_with_suite_name(suite_name):
    request = _canned_test_runner_request()
    request['test']['autotest']['keyvals']['suite'] = suite_name
    return api.properties(TestRunnerProperties(request=request))

  def _request_properties_for_bad_vm_request():
    request = _canned_test_runner_request()
    request['test']['autotest']['keyvals'][
        'build'] = 'betty-arc-r-release/R102-14637.0.0'
    return api.properties(TestRunnerProperties(request=request))

  def _canned_test_runner_request(
      test_arg='foo=bar',
      default_behavior=TestExecutionBehavior.BEHAVIOR_UNSPECIFIED,
      test_name='tauto'):
    return {
        'prejob': {
            'provisionable_labels': {
                'label1': 'value1'
            },
            'software_attributes': {
                'build_target': {
                    'name': 'fake_board',
                },
            },
            'software_dependencies': [
                {
                    'chromeos_build': 'guybrush-release/R105-14989.97.0',
                },
                {
                    'chromeos_build_gcs_bucket': 'chromeos-image-archive',
                },
            ]
        },
        'test': {
            'autotest': {
                'name': test_name,
                'test_args': test_arg,
                'keyvals': {
                    'branch':
                        'release-R105-14989.B',
                    'build':
                        'guybrush-release/R105-14989.97.0',
                    'build_config':
                        'guybrush-release',
                    'cidb_build_id':
                        '5233649',
                    'label':
                        'guybrush-release/R105-14989.97.0/bvt-perbuild/graphics_Idle.arc',
                    'master_build_config':
                        'master-release',
                    'parent_job_id':
                        '5d39c90af9d1ab11',
                    'suite':
                        'bvt-perbuild'
                },
                'is_client_test': True,
                'display_name': 'fancy_name'
            }
        },
        'parent_build_id': 12345,
        'parent_request_uid': 'TestPlanRuns/12345/fake_board-cq.hw.bvt-tast-cq',
        'default_test_execution_behavior': default_behavior,
    }

  def _canned_request_missing_name():
    return {'test': {'autotest': {'display_name': 'name'}}}

  def _canned_multitest_request():
    return {
        'prejob': {
            'provisionable_labels': {
                'label1': 'value1',
                'label2': 'value2',
            },
            'software_attributes': {
                'build_target': {
                    'name': 'fake_board',
                },
            },
            'software_dependencies': [
                {
                    'chromeos_build': 'bob-release/R102-14637.0.0',
                },
                {
                    'chromeos_build_gcs_bucket': 'chromeos-image-archive',
                },
            ]
        },
        'tests': {
            'multi_test_2':
                Request.Test(
                    autotest={
                        'name':
                            'dummy_name',
                        'test_args':
                            'foo=bar',
                        'keyvals': {
                            'branch':
                                'main',
                            'build':
                                'bob-release/R102-14637.0.0',
                            'build_config':
                                'bob-release',
                            'cidb_build_id':
                                '5141110',
                            'datastore_parent_key':
                                "('Build', 5141110)",
                            'label':
                                'bob-release/R102-14637.0.0/bvt-tast-informational/bvt-inline/login_LoginSuccess',
                            'master_build_config':
                                'master-release',
                            'parent_job_id':
                                '59dfe8555444e811',
                            'suite':
                                'bvt-tast-informational'
                        },
                        'is_client_test':
                            True,
                        'display_name':
                            'bob-release/R102-14637.0.0-71034-8802911174428529793/bvt-inline/login_LoginSuccess'
                    }),
        }
    }

  def _canned_milti_duts_request():
    return {
        'prejob': {
            'provisionable_labels': {
                'label1': 'value1'
            },
            'software_attributes': {
                'build_target': {
                    'name': 'fake_board',
                },
            },
            'software_dependencies': [
                {
                    'chromeos_build': 'guybrush-release/R105-14989.97.0',
                },
                {
                    'chromeos_build_gcs_bucket': 'chromeos-image-archive',
                },
            ],
            'secondary_devices': [{
                'software_attributes': {
                    'build_target': {
                        'name': 'fake_board2',
                    }
                },
                'software_dependencies': [{
                    'chromeos_build': 'bob-release/R105-14989.97.0',
                }]
            },]
        },
        'test': {
            'autotest': {
                'name': 'dummy_name',
                'test_args': 'foo=bar',
                'keyvals': {
                    'key1': 'value1',
                },
                'is_client_test': True,
                'display_name': 'fancy_name'
            }
        },
        'parent_build_id': 12345,
        'parent_request_uid': 'TestPlanRuns/12345/fake_board-cq.hw.bvt-tast-cq',
    }

  def _canned_milti_duts_with_android_request():
    return {
        'prejob': {
            'provisionable_labels': {
                'label1': 'value1'
            },
            'software_attributes': {
                'build_target': {
                    'name': 'fake_board',
                },
            },
            'software_dependencies': [
                {
                    'chromeos_build': 'guybrush-release/R105-14989.97.0',
                },
                {
                    'chromeos_build_gcs_bucket': 'chromeos-image-archive',
                },
            ],
            'secondary_devices': [{
                'software_attributes': {
                    'build_target': {
                        'name': 'fake_android_board',
                    }
                }
            },]
        },
        'test': {
            'autotest': {
                'name': 'sample_name',
                'test_args': 'foo=bar',
                'keyvals': {
                    'key1': 'value1',
                },
                'is_client_test': True,
                'display_name': 'fancy_name'
            }
        },
        'parent_build_id': 12345,
        'parent_request_uid': 'TestPlanRuns/12345/fake_board-cq.hw.bvt-tast-cq',
    }

  # Required for steps following `skylab_local_state load`.
  def _mock_load_step(test_id=_DUMMY_TEST_ID):
    return (api.step_data(
        'execution steps.%s.Phosphorus: load skylab local state.call '
        '`phosphorus`.load' % test_id, stdout=api.raw_io.output(
            json_format.MessageToJson(
                load.LoadResponse(
                    results_dir='dummy-results-dir', dut_topology=[
                        load.Dut(hostname='fake_host', board='fake_board',
                                 model='fake_model'),
                    ])))))

  def _successful_prejob_step(test_id=_DUMMY_TEST_ID):
    return _prejob_step_with_state(prejob.PrejobResponse.SUCCEEDED, test_id)

  def _prejob_step_with_state(state, test_id=_DUMMY_TEST_ID):
    return (api.step_data(
        'execution steps.%s.Phosphorus: run prejob.call `phosphorus`.prejob' %
        test_id, stdout=api.raw_io.output(
            json_format.MessageToJson(prejob.PrejobResponse(state=state)))))

  def _successful_run_test_step():
    return _run_test_step_with_state(runtest.RunTestResponse.SUCCEEDED)

  def _run_test_step_with_state(state, test_id=_DUMMY_TEST_ID):
    return (api.step_data(
        'execution steps.%s.Phosphorus: run test.call `phosphorus`.run-test' %
        test_id, stdout=api.raw_io.output(
            json_format.MessageToJson(
                runtest.RunTestResponse(results_dir='dummy-results-dir/subdir',
                                        state=state)))))

  def _successful_fetch_crashes_step(test_id=_DUMMY_TEST_ID):
    return _fetch_crashes_step_with_state(
        fetchcrashes.FetchCrashesResponse.SUCCEEDED, test_id)

  def _fetch_crashes_step_with_state(state, test_id=_DUMMY_TEST_ID):
    return _fetch_crashes_step_with_proto(
        fetchcrashes.FetchCrashesResponse(state=state), test_id)

  def _fetch_crashes_step_with_proto(proto, test_id=_DUMMY_TEST_ID):
    return (api.step_data(
        'execution steps.%s.Phosphorus: fetch crashes.call '
        '`phosphorus`.fetch-crashes' % test_id,
        stdout=api.raw_io.output(json_format.MessageToJson(proto))))

  def _successful_logs_archive_step(test_id=_DUMMY_TEST_ID):
    return api.step_data(
        'execution steps.%s.archive all test logs to Google Storage.'
        'Phosphorus: upload to GS.'
        'call `phosphorus`.upload-to-gs' % test_id, stdout=api.raw_io.output(
            json_format.MessageToJson(
                upload_to_gs.UploadToGSResponse(
                    gs_url='gs://chromeos-test-logs/common-env/UUID/logs'))))

  def _successful_resultdb_upload_step():
    return api.post_process(
        post_process.MustRun, 'execution steps.original_test.' +
        RESULTDB_UPLOAD_STEP + '.upload test results to rdb.run rdb')

  ######## CFT MVP Testing related functions ############

  def mock_metadata(target='test-target'):
    metadata = container_metadata.ContainerMetadata(
        containers={
            target:
                container_metadata.ContainerImageMap(
                    images={
                        'cros-test':
                            container_metadata.ContainerImageInfo(
                                repository=container_metadata.GcrRepository(
                                    hostname='gcr.io',
                                    project='chromeos-bot',
                                ),
                                name='cros-test',
                                digest='sha256:3e36d3622f5adad01080cc2120bb72c0714ecec6118eb9523586410b7435ae80',
                                tags=[
                                    '8835841547076258945',
                                    'amd64-generic-release.R96-1.2.3',
                                ],
                            ),
                    }),
        })
    return metadata

  # An example request.
  def _request_properties_for_ctr(cft_test_request=None):
    if not cft_test_request:
      cft_test_request = _canned_test_runner_request_for_ctr()
    return (api.properties(
        TestRunnerProperties(cft_is_enabled=True,
                             cft_test_request=cft_test_request)))

  def _canned_test_runner_request_for_ctr():
    return {
        'parent_build_id': 12345,
        'primary_dut': {
            'container_metadata_key': 'fake_board',
            'dut_model': {
                'build_target': 'fake_board',
                'model_name': 'fake_model'
            },
            'provision_state': {
                'system_image': {
                    'system_image_path': {
                        'host_type':
                            'GS',
                        'path':
                            'gs://chromeos-image-archive/fake_board-postsubmit/R123-12345.0.0-123456-80000000000',
                    },
                },
            },
        },
        'test_suites': [{
            'execution_metadata': {
                'args': [{
                    'flag': 'bug_id',
                    'value': '12345'
                }, {
                    'flag': 'qual_run_id',
                    'value': '1712172839652'
                }]
            },
            'name': 'suite1',
            'test_case_ids': {
                'test_case_ids': [{
                    'value': 'tauto.stub_Pass'
                }, {
                    'value': 'tast.example.Fail'
                }, {
                    'value': 'tast.example.Pass'
                }]
            }
        }],
        'container_metadata': mock_metadata(),
        'autotest_keyvals': {
            'branch':
                'main',
            'build':
                'bob-release/R102-14637.0.0',
            'build_config':
                'bob-release',
            'cidb_build_id':
                '5141110',
            'datastore_parent_key':
                "('Build', 5141110)",
            'label':
                'bob-release/R102-14637.0.0/bvt-tast-informational/bvt-inline/login_LoginSuccess',
            'master_build_config':
                'master-release',
            'parent_job_id':
                '59dfe8555444e811',
            'suite':
                'bvt-tast-informational'
        }
    }

  def _canned_test_runner_request_for_ctr_gce():
    return {
        'parent_build_id': 12345,
        'primary_dut': {
            'container_metadata_key': 'betty',
            'dut_model': {
                'build_target': 'betty',
                'model_name': 'betty'
            },
            'provision_state': {
                'system_image': {
                    'system_image_path': {
                        'host_type':
                            'GS',
                        'path':
                            'gs://chromeos-image-archive/betty-postsubmit/R123-12345.0.0-123456-80000000000',
                    },
                },
            },
        },
        'test_suites': [{
            'name': 'suite1',
            'test_case_ids': {
                'test_case_ids': [{
                    'value': 'tauto.stub_Pass'
                }, {
                    'value': 'tast.example.Fail'
                }, {
                    'value': 'tast.example.Pass'
                }]
            }
        }],
        'container_metadata': mock_metadata(),
        'autotest_keyvals': {
            'branch':
                'main',
            'build':
                'bob-release/R102-14637.0.0',
            'build_config':
                'bob-release',
            'cidb_build_id':
                '5141110',
            'datastore_parent_key':
                "('Build', 5141110)",
            'label':
                'bob-release/R102-14637.0.0/bvt-tast-informational/bvt-inline/login_LoginSuccess',
            'master_build_config':
                'master-release',
            'parent_job_id':
                '59dfe8555444e811',
            'suite':
                'bvt-tast-informational'
        }
    }

  def _canned_test_runner_request_for_ctr_for_chromium():
    return {
        'parent_build_id': 12345,
        'primary_dut': {
            'container_metadata_key': 'fake_board',
            'dut_model': {
                'build_target': 'fake_board',
                'model_name': 'fake_model'
            },
            'provision_state': {
                'system_image': {
                    'system_image_path': {
                        'host_type':
                            'GS',
                        'path':
                            'gs://chromeos-image-archive/fake_board-postsubmit/R123-12345.0.0-123456-80000000000',
                    },
                },
            },
        },
        'test_suites': [{
            'execution_metadata': {
                'args': [{
                    'flag': 'is_cft',
                    'value': 'True'
                }, {
                    'flag':
                        'lacros_gcs_path',
                    'value':
                        'gs://chrome-test-builds/ash/123_with_patch/base_unittests/lacros_compressed.squash'
                }, {
                    'flag':
                        'resultdb_settings',
                    'value':
                        'eyJiYXNlX3ZhcmlhbnQiOiB7ImJ1aWxkZXIiOiAiY2hyb21lb3Mtdm9sdGVlci1jaHJvbWUtc2t5bGFiIiwgImNyb3NfaW1nIjogIiIsICJkZXZpY2VfdHlwZSI6ICJ2b2x0ZWVyIiwgIm9zIjogIkNocm9tZU9TIiwgInRlc3Rfc3VpdGUiOiAiYmFzZV91bml0dGVzdHMgVk9MVEVFUl9SRUxFQVNFX0xLR00ifSwgImNvZXJjZV9uZWdhdGl2ZV9kdXJhdGlvbiI6IHRydWUsICJlbmFibGUiOiB0cnVlLCAiZXhvbmVyYXRlX3VuZXhwZWN0ZWRfcGFzcyI6IHRydWUsICJoYXNfbmF0aXZlX3Jlc3VsdGRiX2ludGVncmF0aW9uIjogZmFsc2UsICJpbmNsdWRlIjogZmFsc2UsICJyZXN1bHRfYWRhcHRlcl9wYXRoIjogInJlc3VsdF9hZGFwdGVyIiwgInJlc3VsdF9mb3JtYXQiOiAiZ3Rlc3QiLCAic291cmNlcyI6ICJ7XG4gIFwiZ2l0aWxlc0NvbW1pdFwiOiB7XG4gICAgXCJob3N0XCI6IFwiY2hyb21pdW0uZ29vZ2xlc291cmNlLmNvbVwiLFxuICAgIFwicHJvamVjdFwiOiBcImNocm9taXVtL3NyY1wiLFxuICAgIFwicmVmXCI6IFwicmVmcy9oZWFkcy9tYWluXCIsXG4gICAgXCJjb21taXRIYXNoXCI6IFwiMjU5ZGY3MTg4MWFiMGQwYTBmMzQ0MjQxZTM0MGJkN2E3NDIzOWJjY1wiLFxuICAgIFwicG9zaXRpb25cIjogXCIxMjc5MDY1XCJcbiAgfVxufSIsICJ0ZXN0X2lkX2FzX3Rlc3RfbG9jYXRpb24iOiBmYWxzZSwgInRlc3RfaWRfcHJlZml4IjogIm5pbmphOi8vYmFzZTpiYXNlX3VuaXR0ZXN0cy8ifQ=='
                }]
            },
            'name': 'suite1',
            'test_case_ids': {
                'test_case_ids': [{
                    'value': 'tauto.chromium'
                }]
            }
        }],
        'container_metadata': mock_metadata(),
        'autotest_keyvals': {
            'branch':
                'main',
            'build':
                'bob-release/R102-14637.0.0',
            'build_config':
                'bob-release',
            'cidb_build_id':
                '5141110',
            'datastore_parent_key':
                "('Build', 5141110)",
            'label':
                'bob-release/R102-14637.0.0/bvt-tast-informational/bvt-inline/login_LoginSuccess',
            'master_build_config':
                'master-release',
            'parent_job_id':
                '59dfe8555444e811',
            'suite':
                'bvt-tast-informational'
        }
    }

  def _canned_test_runner_request_for_ctr_with_firmware():
    req = _canned_test_runner_request_for_ctr()
    req['primary_dut']['provision_state']['firmware'] = {
        'main_rw_payload': {
            'firmware_image_path': {
                'path': 'some_firmware_path',
            }
        }
    }
    return req

  def _canned_test_runner_request_for_ctr_for_vm():
    req = _canned_test_runner_request_for_ctr_gce()
    req['autotest_keyvals']['build'] = 'betty-arc-r-release/R102-14637.0.0'
    req['test_suites'][0]['name'] = 'arc-cts-vm'
    req['test_suites'][0]['test_case_ids']['test_case_ids'][0][
        'value'] = 'tauto.cheets_CTS_R.internal.arm.CtsPdf'
    return req

  def _canned_test_runner_request_for_ctr_within_deadline(current_time_sec):
    req = _canned_test_runner_request_for_ctr()
    req['deadline'] = timestamp_pb2.Timestamp(seconds=current_time_sec + 55)
    return req

  def _canned_test_runner_request_for_ctr_passed_deadline(current_time_sec):
    req = _canned_test_runner_request_for_ctr()
    req['deadline'] = timestamp_pb2.Timestamp(seconds=current_time_sec - 100)
    return req

  def _canned_test_runner_request_for_ctr_with_missing_field(
      missing_field_name):
    req = _canned_test_runner_request_for_ctr()
    req[missing_field_name] = None
    return req

  def _mock_load_step_for_ctr():
    return (api.step_data(
        'execution steps.CrosToolRunner: Phosphorus: load skylab local state.call '
        '`phosphorus`.load', stdout=api.raw_io.output(
            json_format.MessageToJson(
                load.LoadResponse(
                    results_dir='dummy-results-dir', dut_topology=[
                        load.Dut(hostname='fake_host', board='fake_board',
                                 model='fake_model'),
                    ], lab_dut_topology=[
                        lab_api.dut.DutTopology(
                            id=lab_api.dut.DutTopology.Id(value='fake_host'),
                            duts=[
                                lab_api.dut.Dut(
                                    id=lab_api.dut.Dut.Id(value='fake_host'),
                                    cache_server=lab_api.dut.CacheServer(
                                        address=IpEndpoint(
                                            address='0.0.0.0', port=123)),
                                    chromeos=lab_api.dut.Dut.ChromeOS(
                                        dut_model=lab_api.dut.DutModel(
                                            build_target='fake_board',
                                            model_name='fake_model'),
                                        ssh=IpEndpoint(address='fake_host',
                                                       port=0)))
                            ])
                    ])))))

  def _successful_prejob_step_for_ctr():
    return _provision_step_with_state_for_ctr('success')

  def _failed_prejob_step_for_ctr():
    return _provision_step_with_state_for_ctr(
        'failure', failure_reason=ctr_api.provision_service.InstallFailure
        .Reason.REASON_PROVISIONING_FAILED)

  def _provision_step_with_state_for_ctr(state, failure_reason=None):
    return (api.step_data(
        'execution steps.CrosToolRunner: run provision.call `cros-tool-runner`.provision',
        stdout=api.raw_io.output(
            json_format.MessageToJson(
                cros_tool_runner_cli.CrosToolRunnerProvisionResponse(responses=[
                    _provision_resp_with_state_for_ctr(
                        state=state, failure_reason=failure_reason)
                ])))))

  def _provision_resp_with_state_for_ctr(state, failure_reason=None):
    provision_resp = ctr_api.cros_provision_cli.CrosProvisionResponse(
        id=lab_api.dut.Dut.Id(value='test_dut_host_name'))
    data = {state: {}}
    if state == 'failure' and failure_reason:
      data['failure']['reason'] = failure_reason

    return json_format.ParseDict(data, provision_resp)

  def _successful_run_test_step_for_ctr():
    return _run_test_step_with_state_for_ctr('pass')

  def _skipped_run_test_step_for_ctr():
    return _run_test_step_with_state_for_ctr('skip')

  def _failed_run_test_step_for_ctr():
    return _run_test_step_with_state_for_ctr('fail')

  def _successful_run_test_step_for_ctr_without_result_dir():
    return _run_test_step_with_state_for_ctr('pass', has_result_dir=False)

  def _run_test_step_with_state_for_ctr(state, has_result_dir=True):
    return (api.step_data(
        'execution steps.CrosToolRunner: run test.call `cros-tool-runner`.test',
        stdout=api.raw_io.output(
            json_format.MessageToJson(
                cros_tool_runner_cli.CrosToolRunnerTestResponse(
                    test_case_results=[
                        _test_case_result_resp_with_state_for_ctr(
                            state=state, has_result_dir=has_result_dir)
                    ])))))

  def _test_case_result_resp_with_state_for_ctr(state, has_result_dir=True):
    test_case_result = ctr_api.test_case_result.TestCaseResult(
        test_case_id=ctr_api.test_case.TestCase.Id(value='tauto.dummy_id'),
        test_harness=ctr_api.test_harness.TestHarness(
            tauto=ctr_api.test_harness.TestHarness.Tauto()),
        result_dir_path=StoragePath(
            host_type=StoragePath.HostType.LOCAL,
            path='dummy-results-dir/subdir' if has_result_dir else ''),
        reason='reason', start_time=timestamp_pb2.Timestamp(seconds=2369692800),
        duration=duration_pb2.Duration(seconds=3600))
    data = {state: {}}
    return json_format.ParseDict(data, test_case_result)

  def _crossystem_keyval_file_step_data_for_ctr():
    return api.step_data(
        'execution steps.read crossystem keyval file',
        api.file.read_text('''
fw_prev_result          = success                        # [RO/str] Firmware result of previous boot
fw_prev_tried           = B                              # [RO/str] Firmware tried on previous boot (A or B)
fw_result               = success                        # [RW/str] Firmware result this boot
fw_tried                = B                              # [RO/str] Firmware tried this boot (A or B)
fw_try_count            = 0                              # [RW/int] Number of times to try fw_try_next
fw_try_next             = B                              # [RW/str] Firmware to try next (A or B)
fw_vboot2               = 1                              # [RO/int] 1 if firmware was selected by vboot2 or 0 otherwise
fwb_tries               = 0                              # [RW/int] Try firmware B count
fwid                    = Google_Voema.13672.224.0       # [RO/str] Active firmware ID
fwupdate_tries          = 0                              # [RW/int] Times to try OS firmware update (inside kern_nv)
hwid                    = VOEMA-DHAS C4B-D3A-C3C-37Y-A83 # [RO/str] Hardware ID
ro_fwid                 = Google_Voema.13672.224.0       # [RO/str] Read-only firmware ID
    '''))

  def _gsctool_keyval_file_step_data_for_ctr():
    return api.step_data(
        'execution steps.read gsctool keyval file',
        api.file.read_text('''
start
target running protocol version 6
keyids: RO 0xc7d40497, RW 0xfba25ca9
offsets: backup RO at 0, backup RW at 0x4000
Current versions:
RO 0.0.38
RW 0.24.13
    '''))

  def _servo_keyval_file_step_data_for_ctr():
    return api.step_data(
        'execution steps.read servo keyval file',
        api.file.read_text('''
ccd_cr50_version.ccd_flex_secondary=0.6.190/cr50_v3.94_pp.192-3677cf40af
servo_host_os_version=fizz-labstation-release/R114-15437.59.0
servo_micro_version.main=servo_micro_v2.4.73-d771c18ba9
servo_type=servo_v4_with_servo_micro_and_ccd_cr50
servo_v4_version.root=servo_v4_v2.4.58-c37246f9c
servod_version=v1.0.1732-67007a28 2023-06-20 19:22:43
    '''))

  def _kernel_log_file_step_data_for_ctr():
    return api.step_data(
        'execution steps.read kernel log file',
        api.file.read_text('''
Linux localhost 5.4.190-18482-g9cffa68a11c1 #1 SMP PREEMPT Wed Apr 27 18:24:08 PDT 2022 x86_64 Intel(R) Core(TM) i7-7Y75 CPU @ 1.30GHz GenuineIntel GNU/Linux
    '''))

  ########## Test cases #########

  yield api.test(
      'test-name-missing',
      _misc_properties(),
      _request_properties_no_name(),
      status='FAILURE',
  )

  yield api.test(
      'success',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )
  yield api.test(
      'success-misconfigured-prejob',
      _set_build(bid=42),
      _misc_properties(non_compliant_prejob_deadline=True),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-result-publishing-experiment-success',
      _set_build(bid=42),
      _misc_properties(use_result_publishing_limit=True),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-tast-autotest-keyval-file',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      api.properties(result_format='tast'),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read autotest keyval file',
          api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tast_test_result_file_step_data(),
      _mock_autotest_wrapper_tast_result(),
      _autotest_wrapper_tast_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-parent-crossystem-keyval-file-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read crossystem keyval file',
          api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-parent-and-child-crossystem-keyval-files-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      # Sets the test case so that it can use the test case name to find the
      # child directory.
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(test_cases=[
                          Result.Autotest.TestCase(
                              name='pass_test_case_1',
                              verdict=Result.Autotest.TestCase.VERDICT_PASS),
                      ]),
                  )))),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read crossystem keyval file',
          api.file.read_text(errno_name='file does not exist')),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read crossystem keyval file (2)',
          api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-parent-gsctool-keyval-file-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read gsctool keyval file',
          api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-parent-and-child-gsctool-keyval-files-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      # Sets the test case so that it can use the test case name to find the
      # child directory.
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(test_cases=[
                          Result.Autotest.TestCase(
                              name='pass_test_case_1',
                              verdict=Result.Autotest.TestCase.VERDICT_PASS),
                      ]),
                  )))),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read gsctool keyval file',
          api.file.read_text(errno_name='file does not exist')),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read gsctool keyval file (2)',
          api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-parent-servo-keyval-file-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read servo keyval file',
          api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-parent-and-child-servo-keyval-files-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      # Sets the test case so that it can use the test case name to find the
      # child directory.
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(test_cases=[
                          Result.Autotest.TestCase(
                              name='pass_test_case_1',
                              verdict=Result.Autotest.TestCase.VERDICT_PASS),
                      ]),
                  )))),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read servo keyval file',
          api.file.read_text(errno_name='file does not exist')),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read servo keyval file (2)',
          api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-parent-kernel-log-file-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read kernel log file',
          api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-parent-and-child-kernel-log-file-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      # Sets the test case so that it can use the test case name to find the
      # child directory.
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(test_cases=[
                          Result.Autotest.TestCase(
                              name='pass_test_case_1',
                              verdict=Result.Autotest.TestCase.VERDICT_PASS),
                      ]),
                  )))),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read kernel log file',
          api.file.read_text(errno_name='file does not exist')),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read kernel log file (2)',
          api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'no-test-result-file-and-skip-resultdb-upload',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
              'test-plan-id': 'fake_testplan',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read test results from test_runner_result.json',
          api.file.read_text(errno_name='file does not exist')),
      api.post_process(
          post_process.DoesNotRun, 'execution steps.original_test.' +
          RESULTDB_UPLOAD_STEP + '.upload test results to rdb.run rdb'),
  )

  yield api.test(
      'success-with-resultdb-tast',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
              'test-plan-id': 'ltl_testplan',
              'qs_account': 'unmanaged_p2',
              'ctp-fwd-task-name': 'Bluetooth_Sa_Perbuild',
              'branch-trigger': 'DEV',
          }, swarming_tags={
              'drone':
                  'fake-drone-1234',
              'drone_server':
                  'fakeserver1-row2-drone3',
              'dut_name':
                  'fakedut1-row2-rack3-host4',
              'pool':
                  'ChromeOSSkylab',
              'label-wifi_chip':
                  'marvell',
              'label-wifi_router_models':
                  'gale',
              'label-hwid_sku':
                  'katsu_MT8183_0B',
              'label-pool':
                  'DUT_POOL_QUOTA',
              'label-carrier':
                  'fake-carrier',
              'label-cbx':
                  'True',
              'label-chameleon_type':
                  'CHAMELEON_TYPE_HDMI',
              'label-modem_type':
                  'MODEM_TYPE_FIBOCOMM_L850GL',
              'label-dlm_sku_id':
                  '1234',
              'ufs_zone':
                  'ZONE_SFO36_OS',
              'label-chameleon_connection_types':
                  'CHAMELEON_CONNECTION_TYPE_USB',
          }),
      api.properties(result_format='tast'),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Reads rich info for the ResultDB upload.
      _autotest_keyval_file_step_data(),
      _crossystem_keyval_file_step_data(),
      _gsctool_keyval_file_step_data(),
      _servo_keyval_file_step_data(),
      _kernel_log_file_step_data(),
      # Enables the ResultDB upload.
      _tast_test_result_file_step_data(),
      _mock_autotest_wrapper_tast_result(),
      _autotest_wrapper_tast_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-with-resultdb-tast-partner-accound-id',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
              'test-plan-id': 'ltl_testplan',
              'qs_account': 'unmanaged_p2',
              'ctp-fwd-task-name': 'Bluetooth_Sa_Perbuild',
              'branch-trigger': 'DEV',
          }, swarming_tags={
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
              'label-wifi_router_models': 'gale',
              'label-hwid_sku': 'katsu_MT8183_0B',
              'label-pool': 'DUT_POOL_QUOTA',
              'label-carrier': 'fake-carrier',
              'label-cbx': 'True',
              'label-chameleon_type': 'CHAMELEON_TYPE_HDMI',
              'label-modem_type': 'MODEM_TYPE_FIBOCOMM_L850GL',
              'ufs_zone': 'ZONE_SFO36_OS',
          }),
      api.properties(result_format='tast'),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      api.properties(
          TestRunnerProperties(
              common_config={'partner_config': {
                  'account_id': 4
              }})),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Reads rich info for the ResultDB upload.
      _autotest_keyval_file_step_data(),
      _crossystem_keyval_file_step_data(),
      _gsctool_keyval_file_step_data(),
      _servo_keyval_file_step_data(),
      _kernel_log_file_step_data(),
      # Enables the ResultDB upload.
      _tast_test_result_file_step_data(),
      _mock_autotest_wrapper_tast_result(),
      _autotest_wrapper_tast_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-with-resultdb-tast-with-duplicate-swarming-bot-dimensions',
      _set_build(
          bid=42,
          tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test',
              'test-plan-id': 'ltl_testplan',
          },
          swarming_tags={
              # Duplicate chameleon_type labels.
              'label-chameleon_type': [
                  'CHAMELEON_TYPE_HDMI', 'CHAMELEON_TYPE_V3'
              ],
              'label-chameleon_connection_types': [
                  'CHAMELEON_CONNECTION_TYPE_USB',
                  'CHAMELEON_CONNECTION_TYPE_HDMI'
              ],
          }),
      api.properties(result_format='tast'),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Reads rich info for the ResultDB upload.
      _autotest_keyval_file_step_data(),
      _crossystem_keyval_file_step_data(),
      _gsctool_keyval_file_step_data(),
      _servo_keyval_file_step_data(),
      _kernel_log_file_step_data(),
      # Enables the ResultDB upload.
      _tast_test_result_file_step_data(),
      _mock_autotest_wrapper_tast_result(),
      _autotest_wrapper_tast_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-with-resultdb-tast-with-swarming-task-dimensions',
      # The label-pool "satlab_tp101" in the swarming task dimensions will be
      # uploaded instead of the first one "satlab_faft" in the bot dimensions.
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test'
          }, swarming_tags={
              'label-pool': ['satlab_faft', 'satlab_tam', 'satlab_tp101']
          }, swarming_task_dimensions=[
              common_pb2.RequestedDimension(
                  key='label-pool',
                  value='satlab_tp101',
              )
          ]),
      api.properties(result_format='tast'),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Reads rich info for the ResultDB upload.
      _autotest_keyval_file_step_data(),
      _crossystem_keyval_file_step_data(),
      _gsctool_keyval_file_step_data(),
      _servo_keyval_file_step_data(),
      _kernel_log_file_step_data(),
      # Enables the ResultDB upload.
      _tast_test_result_file_step_data(),
      _mock_autotest_wrapper_tast_result(),
      _autotest_wrapper_tast_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-with-resultdb-tast-with-missing-bb-tags',
      _set_build(
          bid=42,
          tags={
              # Falls back to the `label-image` label if the `build` label is
              # missing.
              # Context: b/244294904
              'label-image': 'fake-board-cq/R11-123.45',
              'suite': 'fake-suite',
              'display_name': 'fake-board-cq/R11-123.45/fake-suite/fake-test'
          },
          swarming_tags={
              # Fetches board and model info from swarming tags if they
              # are missing in buildbucket tags.
              # Context: b/244297392
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'drone': 'fake-drone-1234',
              'drone_server': 'fakeserver1-row2-drone3',
              'dut_name': 'fakedut1-row2-rack3-host4',
              'pool': 'ChromeOSSkylab',
              'label-wifi_chip': 'marvell',
          }),
      api.properties(result_format='tast'),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Reads rich info for the ResultDB upload.
      _autotest_keyval_file_step_data(),
      _crossystem_keyval_file_step_data(),
      _gsctool_keyval_file_step_data(),
      _servo_keyval_file_step_data(),
      _kernel_log_file_step_data(),
      # Enables the ResultDB upload.
      _tast_test_result_file_step_data(),
      _mock_autotest_wrapper_tast_result(),
      _autotest_wrapper_tast_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-with-resultdb-multiduts-tast',
      _set_build(
          bid=42, tags={
              'primary_board': 'fake-board',
              'secondary_boards': 'fake-secondary-board',
              'primary_model': 'fake-model',
              'secondary_models': 'fake-secondary-model',
          }, swarming_tags={
              'label-multiduts': 'True',
          }),
      api.properties(result_format='tast'),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Reads rich info for the ResultDB upload.
      _autotest_keyval_file_step_data(),
      _crossystem_keyval_file_step_data(),
      _gsctool_keyval_file_step_data(),
      _servo_keyval_file_step_data(),
      _kernel_log_file_step_data(),
      # Enables the ResultDB upload.
      _tast_test_result_file_step_data(),
      _mock_autotest_wrapper_tast_result(),
      _autotest_wrapper_tast_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-multi-duts',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_multiduts(),
      api.step_data(
          'execution steps.original_test.Phosphorus: load skylab local state.'
          'call `phosphorus`.load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  load.LoadResponse(
                      results_dir='dummy-results-dir', dut_topology=[
                          load.Dut(hostname='fake_hostname', board='fake_board',
                                   model='fake_model'),
                          load.Dut(hostname='fake_hostname2',
                                   board='fake_board2', model='fake_model2')
                      ])))),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-multi-duts-with-android-devices',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_multiduts_with_androids(),
      api.step_data(
          'execution steps.original_test.Phosphorus: load skylab local state.'
          'call `phosphorus`.load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  load.LoadResponse(
                      results_dir='dummy-results-dir', dut_topology=[
                          load.Dut(hostname='fake_hostname', board='fake_board',
                                   model='fake_model'),
                          load.Dut(hostname='fake_hostname2',
                                   board='fake_android_board',
                                   model='fake_android_model')
                      ])))),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  r_with_deadline = _canned_test_runner_request()
  r_with_passed_deadline = _canned_test_runner_request()
  current_time_sec = 2369692800
  test_deadline = timestamp_pb2.Timestamp(seconds=current_time_sec - 100)
  r_with_deadline['deadline'] = timestamp_pb2.Timestamp(
      seconds=current_time_sec + 55)
  r_with_passed_deadline['deadline'] = test_deadline

  yield api.test(
      'deadline-passed',
      api.time.seed(current_time_sec),
      _misc_properties(),
      api.properties(TestRunnerProperties(request=r_with_passed_deadline)),
      _mock_load_step(),
      _successful_logs_archive_step(),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'success-with-build-deadline',
      api.time.seed(current_time_sec),
      api.buildbucket.build(_build_with_execution_timeout(30)),
      _misc_properties(),
      api.properties(TestRunnerProperties(request=r_with_deadline)),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'success-with-request-deadline',
      api.time.seed(current_time_sec),
      api.buildbucket.build(_build_with_execution_timeout(66)),
      _misc_properties(),
      api.properties(TestRunnerProperties(request=r_with_deadline)),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'success-with-timestamp-in-results',
      _set_build(bid=42),
      _autotest_keyval_file_step_data(),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(test_cases=[
                          Result.Autotest.TestCase(
                              name='pass_test_case_1',
                              verdict=Result.Autotest.TestCase.VERDICT_PASS),
                          Result.Autotest.TestCase(
                              name='pass_test_case_2',
                              verdict=Result.Autotest.TestCase.VERDICT_PASS)
                      ]))))),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-without-timestamps-in-results',
      _set_build(bid=42),
      _autotest_keyval_file_step_data_no_timestamps(),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(test_cases=[
                          Result.Autotest.TestCase(
                              name='pass_test_case_1',
                              verdict=Result.Autotest.TestCase.VERDICT_PASS),
                          Result.Autotest.TestCase(
                              name='pass_test_case_2',
                              verdict=Result.Autotest.TestCase.VERDICT_PASS)
                      ]))))),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-with-ancestor-ids-for-resultdb',
      _set_build(bid=42, ancestor_buildbucket_ids=[123, 456]),
      api.properties(result_format='tast'),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Reads rich info for the ResultDB upload.
      _autotest_keyval_file_step_data(),
      _crossystem_keyval_file_step_data(),
      _gsctool_keyval_file_step_data(),
      _servo_keyval_file_step_data(),
      _kernel_log_file_step_data(),
      # Enables the ResultDB upload.
      _tast_test_result_file_step_data(),
      _mock_autotest_wrapper_tast_result(),
      _autotest_wrapper_tast_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-with-full-test-name-for-autotest',
      _set_build(
          bid=42,
          tags={
              'label-board':
                  'fake-board',
              'label-model':
                  'fake-model',
              'build':
                  'fake-board-cq/R11-123.45',
              'suite':
                  'fake-suite',
              # Contains the full test name.
              'display_name':
                  'fake-board-cq/R11-123.45/fake-suite/pass_test_case_1_full'
          }),
      _autotest_keyval_file_step_data(),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(test_cases=[
                          Result.Autotest.TestCase(
                              name='pass_test_case_1',
                              verdict=Result.Autotest.TestCase.VERDICT_PASS)
                      ]))))),
      # Enables the ResultDB upload.
      _tauto_test_result_file_step_data(),
      _successful_resultdb_upload_step(),
  )

  yield api.test(
      'success-with-incomplete-test-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board':
                  'fake-board',
              'label-model':
                  'fake-model',
              'build':
                  'bob-release/R102-14637.0.0-71034-8802911174428529793',
              'suite':
                  'bvt-inline',
              'display_name':
                  'bob-release/R102-14637.0.0-71034-8802911174428529793/bvt-inline/login_LoginSuccess'
          }),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Returns incomplete test.
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(incomplete=True),
                      prejob=Result.Prejob(step=[
                          Result.Prejob.Step(
                              name='provision',
                              human_readable_summary='failed prejob',
                              verdict=Result.Prejob.Step.VERDICT_FAIL)
                      ]))))),
      _autotest_keyval_file_step_data(),
      # Skips the ResultDB upload for incomplete tests.
      api.post_process(
          post_process.DoesNotRun, 'execution steps.original_test.' +
          RESULTDB_UPLOAD_STEP + '.upload test results to rdb.run rdb'),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'success-with-incomplete-test-for-tast',
      _set_build(
          bid=42, tags={
              'label-board':
                  'fake-board',
              'label-model':
                  'fake-model',
              'build':
                  'bob-release/R102-14637.0.0-71034-8802911174428529793',
              'suite':
                  'bvt-inline',
              'display_name':
                  'bob-release/R102-14637.0.0-71034-8802911174428529793/bvt-inline/tast.login_LoginSuccess'
          }),
      api.properties(result_format='tast'),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Returns incomplete test.
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(incomplete=True),
                      prejob=Result.Prejob(step=[
                          Result.Prejob.Step(
                              name='provision',
                              human_readable_summary='failed prejob',
                              verdict=Result.Prejob.Step.VERDICT_FAIL)
                      ]))))),
      _autotest_keyval_file_step_data(),
      # Skips the ResultDB upload for incomplete tests.
      api.post_process(
          post_process.DoesNotRun, 'execution steps.original_test.' +
          RESULTDB_UPLOAD_STEP + '.upload test results to rdb.run rdb'),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'success-with-failed-prejob-step-for-tauto',
      _set_build(
          bid=42, tags={
              'label-board':
                  'fake-board',
              'label-model':
                  'fake-model',
              'build':
                  'bob-release/R102-14637.0.0-71034-8802911174428529793',
              'suite':
                  'bvt-inline',
              'display_name':
                  'bob-release/R102-14637.0.0-71034-8802911174428529793/bvt-inline/login_LoginSuccess'
          }),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      # Prejob failed and then caused the test execution step skipped.
      _prejob_step_with_state(prejob.PrejobResponse.FAILED),
      _successful_logs_archive_step(),
      # Returns incomplete test.
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(autotest_result=Result.Autotest(incomplete=True))))),
      _autotest_keyval_file_step_data(),
      # Skips the ResultDB upload for incomplete tests due to the failed prejob.
      api.post_process(
          post_process.DoesNotRun, 'execution steps.original_test.' +
          RESULTDB_UPLOAD_STEP + '.upload test results to rdb.run rdb'),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'prejob-crash',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: run prejob.call '
          '`phosphorus`.prejob', retcode=1),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'run-test-crash',
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: run test.call '
          '`phosphorus`.run-test', retcode=1),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'upload-to-resultdb-crash',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      # Enables the ResultDB upload.
      api.properties(result_format='tast'),
      _tast_test_result_file_step_data(),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.upload test results to rdb.run rdb', retcode=1),
      # The resultdb upload failure above won't block the following steps.
      api.post_process(
          post_process.MustRun,
          'execution steps.Phosphorus: remove autotest results dir'),
  )

  yield api.test(
      'upload-autotest-wrapper-result-to-resultdb-crash',
      _set_build(bid=42),
      api.properties(result_format='tast'),
      _misc_properties(),
      # Sets Tast test name in the test request for Autotest wrapper result
      # upload.
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL, 'tast.critical-system-shard-2'),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      _tast_test_result_file_step_data(),
      _mock_autotest_wrapper_tast_result(),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.read test results from autotest_wrapper_tast_result.json',
          retcode=1),
      # The autotest wrapper result rdb upload failure above won't block the
      # following steps.
      api.post_process(
          post_process.MustRun,
          'execution steps.Phosphorus: remove autotest results dir'),
  )

  yield api.test(
      'link-to-all-archived-logs',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(test_cases=[]),
                  )))),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'get-results-crash',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.'
          'call `phosphorus`.parse', retcode=1),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'results-summary',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: get test results.call '
          '`phosphorus`.'
          'parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      prejob=Result.Prejob(step=[
                          Result.Prejob.Step(
                              name='failing_prejob_step',
                              human_readable_summary='failed prejob',
                              verdict=Result.Prejob.Step.VERDICT_FAIL)
                      ]), autotest_result=Result.Autotest(
                          test_cases=[
                              Result.Autotest.TestCase(
                                  name='failing_test_case',
                                  human_readable_summary='failing test case',
                                  verdict=Result.Autotest.TestCase.VERDICT_FAIL)
                          ], incomplete=True))))),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'failed-prejob-with-missing-failures-in-result',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _prejob_step_with_state(prejob.PrejobResponse.FAILED),
      _successful_logs_archive_step(),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'failed-runtest-with-missing-failures-in-result',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _run_test_step_with_state(runtest.RunTestResponse.FAILED),
      _successful_logs_archive_step(),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'successful-runtest-with-multiple-tests',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_multitest(),
      _mock_load_step(test_id='multi_test_2'),
      _successful_prejob_step(test_id='multi_test_2'),
      _run_test_step_with_state(runtest.RunTestResponse.SUCCEEDED,
                                test_id='multi_test_2'),
      _successful_fetch_crashes_step(test_id='multi_test_2'),
      _successful_logs_archive_step(test_id='multi_test_2'),
  )

  yield api.test(
      'failed-fetchcrashes',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _fetch_crashes_step_with_state(runtest.RunTestResponse.FAILED),
      _successful_logs_archive_step(),
  )

  fetch_crashes_proto = fetchcrashes.FetchCrashesResponse(
      state=runtest.RunTestResponse.SUCCEEDED, crashes_rtd_only=['foobar.meta'])
  yield api.test(
      'successful-fetchcrashes-with-missed-crashes',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _fetch_crashes_step_with_proto(fetch_crashes_proto),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'skip-result-flow-pubsub-due-to-missing-build-ID',
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'skip-result-flow-pubsub-due-to-missing-topic',
      _set_build(bid=42),
      _misc_properties(),
      api.properties(
          TestRunnerProperties(
              config={
                  'result_flow_pubsub': {
                      'topic': '',
                      'project': 'foo-proj',
                  },
                  'output': {
                      'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
                  },
              })),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'skip-result-flow-pubsub-due-to-missing-project',
      _set_build(bid=42),
      _misc_properties(),
      api.properties(
          TestRunnerProperties(
              config={
                  'result_flow_pubsub': {
                      'topic': 'foo-topic',
                      'project': '',
                  },
                  'output': {
                      'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
                  },
              })),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  rdb_settings = {
      'result_format': 'tast',
      'base_tags': ['test_suite:lacros_all_tast_tests'],
      'base_variant': {
          'test_suite': 'lacros_all_tast_tests',
      },
  }
  yield api.test(
      'chromium-test-upload-result-to-rdb',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_rdb(
          api.cros_resultdb.resultdb_settings_arg(rdb_settings)),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      _autotest_keyval_file_step_data(),
      api.post_process(
          post_process.StepCommandContains,
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.upload chromium test results '
          'to rdb.run rdb',
          [
              '[START_DIR]/cipd/result_adapter/result_adapter',
              'tast',
              '-result-file',
              'dummy-results-dir/autoserv_test/tast/results/streamed_results.jsonl',
              '-artifact-directory',
              'dummy-results-dir/autoserv_test',
          ],
      ),
      api.post_process(
          post_process.MustRun, 'execution steps.original_test.' +
          RESULTDB_UPLOAD_STEP + '.upload chromium test results to rdb.'
          'run rdb'),
  )

  yield api.test(
      'chromium-test-upload-result-to-rdb-failure',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_rdb(
          api.cros_resultdb.resultdb_settings_arg(rdb_settings)),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      api.step_data(
          'execution steps.original_test.' + RESULTDB_UPLOAD_STEP +
          '.upload chromium test results '
          'to rdb.run rdb', retcode=1),
      api.post_process(
          post_process.StepFailure, 'execution steps.'
          'original_test.' + RESULTDB_UPLOAD_STEP +
          '.upload chromium test results to rdb'),
      api.post_process(
          post_process.MustRun,
          'execution steps.Phosphorus: remove autotest results dir'),
  )

  yield api.test(
      'dut_topology_experiment-flag',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      api.properties(
          TestRunnerProperties(
              config={
                  'prejob_step': {
                      'dut_topology_experiment': {
                          'enabled': True,
                          'test_allowlist': [],
                          'suite_allowlist': [],
                      }
                  },
                  'result_flow_pubsub': {
                      'topic': 'foo-topic',
                      'project': '',
                  },
                  'output': {
                      'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
                  },
              })),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'dut_topology-test_allowlist',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      api.properties(
          TestRunnerProperties(
              config={
                  'prejob_step': {
                      'dut_topology_experiment': {
                          'enabled': False,
                          'test_allowlist': ['dummy_name'],
                          'suite_allowlist': [],
                      }
                  },
                  'result_flow_pubsub': {
                      'topic': 'foo-topic',
                      'project': '',
                  },
                  'output': {
                      'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
                  },
              })),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'dut_topology-suite_allowlist',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_with_suite_name('dummy_suite'),
      api.properties(
          TestRunnerProperties(
              config={
                  'prejob_step': {
                      'dut_topology_experiment': {
                          'enabled': False,
                          'test_allowlist': [],
                          'suite_allowlist': ['dummy_suite'],
                      }
                  },
                  'result_flow_pubsub': {
                      'topic': 'foo-topic',
                      'project': '',
                  },
                  'output': {
                      'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
                  },
              })),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'cros_firmware_update_config-allow_list',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      api.properties(
          TestRunnerProperties(
              common_config={
                  'cros_firmware_update_config': {
                      'enabled': True,
                      'allow_list': {
                          'boards': [],
                          'models': []
                      }
                  }
              })),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'cros_firmware_update_config-block_list',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      api.properties(
          TestRunnerProperties(
              common_config={
                  'cros_firmware_update_config': {
                      'enabled': True,
                      'block_list': {
                          'boards': [],
                          'models': []
                      }
                  }
              })),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  # Ile-de-France allow list tests whether the logic
  # for an allowed board works correctly.
  yield api.test(
      'ile-de-france-allow_list',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      api.properties(
          TestRunnerProperties(
              common_config={
                  'enable_ile_de_france_config': {
                      'enabled': True,
                      'allow_list': {
                          'models': []
                      }
                  }
              })),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  # Ile-de-France deny list tests whether the logic
  # for a blocked board works correctly.
  yield api.test(
      'ile-de-france-block_list',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      api.properties(
          TestRunnerProperties(
              common_config={
                  'enable_ile_de_france_config': {
                      'enabled': True,
                      'deny_list': {
                          'models': []
                      }
                  }
              })),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'fail-vm-on-phosphorus',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_for_bad_vm_request(),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  ############ CTR Test Cases ##########

  yield api.test('success-with-ctr', _set_build(bid=42),
                 _misc_properties(cft_is_enabled=True),
                 _crossystem_keyval_file_step_data_for_ctr(),
                 _gsctool_keyval_file_step_data_for_ctr(),
                 _servo_keyval_file_step_data_for_ctr(),
                 _kernel_log_file_step_data_for_ctr(),
                 _request_properties_for_ctr(), _mock_load_step_for_ctr(),
                 _successful_prejob_step_for_ctr(),
                 _successful_run_test_step_for_ctr())

  yield api.test('skipped-with-ctr', _set_build(bid=42),
                 _misc_properties(cft_is_enabled=True),
                 _crossystem_keyval_file_step_data_for_ctr(),
                 _gsctool_keyval_file_step_data_for_ctr(),
                 _servo_keyval_file_step_data_for_ctr(),
                 _kernel_log_file_step_data_for_ctr(),
                 _request_properties_for_ctr(), _mock_load_step_for_ctr(),
                 _successful_prejob_step_for_ctr(),
                 _skipped_run_test_step_for_ctr())

  yield api.test('success-with-ctr-without-result-dir', _set_build(bid=42),
                 _misc_properties(cft_is_enabled=True),
                 _request_properties_for_ctr(), _mock_load_step_for_ctr(),
                 _successful_prejob_step_for_ctr(),
                 _successful_run_test_step_for_ctr_without_result_dir())

  yield api.test(
      'success-with-ctr-misconfigured-prejob', _set_build(bid=42),
      _misc_properties(cft_is_enabled=True, non_compliant_prejob_deadline=True),
      _crossystem_keyval_file_step_data_for_ctr(),
      _gsctool_keyval_file_step_data_for_ctr(),
      _servo_keyval_file_step_data_for_ctr(),
      _kernel_log_file_step_data_for_ctr(), _request_properties_for_ctr(),
      _mock_load_step_for_ctr(), _successful_prejob_step_for_ctr(),
      _successful_run_test_step_for_ctr())

  yield api.test(
      'success-with-ctr-result-publishing-experiment', _set_build(bid=42),
      _misc_properties(cft_is_enabled=True, use_result_publishing_limit=True),
      _crossystem_keyval_file_step_data_for_ctr(),
      _gsctool_keyval_file_step_data_for_ctr(),
      _servo_keyval_file_step_data_for_ctr(),
      _kernel_log_file_step_data_for_ctr(), _request_properties_for_ctr(),
      _mock_load_step_for_ctr(), _successful_prejob_step_for_ctr(),
      _successful_run_test_step_for_ctr())

  yield api.test(
      'success-with-ctr-gce',
      _set_build(bid=42),
      _misc_properties(cft_is_enabled=True),
      _crossystem_keyval_file_step_data_for_ctr(),
      _gsctool_keyval_file_step_data_for_ctr(),
      _servo_keyval_file_step_data_for_ctr(),
      _kernel_log_file_step_data_for_ctr(),
      _request_properties_for_ctr(
          cft_test_request=_canned_test_runner_request_for_ctr_for_vm()),
      _successful_run_test_step_for_ctr(),
  )

  yield api.test(
      'success-with-ctr-for-chromium', _set_build(bid=42),
      _misc_properties(cft_is_enabled=True),
      _crossystem_keyval_file_step_data_for_ctr(),
      _gsctool_keyval_file_step_data_for_ctr(),
      _servo_keyval_file_step_data_for_ctr(),
      _kernel_log_file_step_data_for_ctr(),
      _request_properties_for_ctr(
          cft_test_request=_canned_test_runner_request_for_ctr_for_chromium()),
      _mock_load_step_for_ctr(), _successful_prejob_step_for_ctr(),
      _successful_run_test_step_for_ctr())

  yield api.test(
      'within-deadline-ctr', api.time.seed(2369692800),
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(
          cft_test_request=_canned_test_runner_request_for_ctr_within_deadline(
              current_time_sec=2369692800)), _mock_load_step_for_ctr(),
      _successful_prejob_step_for_ctr(), _successful_run_test_step_for_ctr())

  yield api.test(
      'deadline-passed-ctr',
      api.time.seed(2369692800),
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(
          cft_test_request=_canned_test_runner_request_for_ctr_passed_deadline(
              current_time_sec=2369692800)),
      _mock_load_step_for_ctr(),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'primary-dut-missing',
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(
          cft_test_request=_canned_test_runner_request_for_ctr_with_missing_field(
              missing_field_name='primary_dut')),
      status='FAILURE',
  )

  yield api.test(
      'test-suites-missing',
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(
          cft_test_request=_canned_test_runner_request_for_ctr_with_missing_field(
              missing_field_name='test_suites')),
      status='FAILURE',
  )

  yield api.test(
      'provision-crash-ctr',
      _set_build(bid=42),
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(),
      _mock_load_step_for_ctr(),
      api.step_data(
          'execution steps.CrosToolRunner: run provision.call `cros-tool-runner`.provision',
          retcode=1),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'run-test-crash-ctr',
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(),
      _mock_load_step_for_ctr(),
      _successful_prejob_step_for_ctr(),
      api.step_data(
          'execution steps.CrosToolRunner: run test.call `cros-tool-runner`.test',
          retcode=1),
      status='FAILURE',
  )

  yield api.test(
      'provision-failed-ctr',
      _set_build(bid=42),
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(),
      _mock_load_step_for_ctr(),
      _failed_prejob_step_for_ctr(),
      status='FAILURE',
  )

  yield api.test(
      'test-failed-ctr',
      _set_build(bid=42),
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(),
      _mock_load_step_for_ctr(),
      _successful_prejob_step_for_ctr(),
      _failed_run_test_step_for_ctr(),
      status='FAILURE',
  )

  yield api.test(
      'fetch-sources-failed-ctr',
      _set_build(bid=42),
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(),
      _mock_load_step_for_ctr(),
      _successful_prejob_step_for_ctr(),
      _successful_run_test_step_for_ctr(),
      api.step_data(
          'execution steps.identify sources under test.gsutil download metadata/sources.jsonpb',
          retcode=1),
      # It is possible the sources file will not exist in Google Storage.
      # We should handle this case gracefully.
      status='SUCCESS',
  )

  yield api.test(
      'sources-dirty-due-to-firmware-ctr',
      _set_build(bid=42),
      _misc_properties(cft_is_enabled=True),
      _request_properties_for_ctr(
          cft_test_request=_canned_test_runner_request_for_ctr_with_firmware(),
      ),
      _mock_load_step_for_ctr(),
      _successful_prejob_step_for_ctr(),
      _successful_run_test_step_for_ctr(),
      status='SUCCESS',
  )
