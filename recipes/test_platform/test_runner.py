# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Skylab Test Runner."""
import base64
import os

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.phosphorus.phosphorus \
  import PhosphorusProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus\
  import PhosphorusEnvProperties
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner \
  import CrosToolRunnerProperties
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner\
  import CrosToolRunnerEnvProperties
from PB.recipes.chromeos.test_platform.test_runner import TestRunnerProperties
from PB.test_platform import phosphorus
from PB.test_platform.request import Request as TestPlatformRequest
from PB.test_platform import skylab_local_state
from PB.test_platform.skylab_test_runner.result import Result
from PB.test_platform.skylab_test_runner.request import Request
from PB.chromiumos.test import api as ctr_api
from PB.chromiumos.test.lab import api as lab_api
from PB.chromiumos.storage_path import StoragePath
from PB.chromiumos.build.api import container_metadata
from PB.chromiumos.test.lab.api.ip_endpoint import IpEndpoint

from google.protobuf import duration_pb2
from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.dut_interface import dut_interface, error_messages

PYTHON_VERSION_COMPATIBILITY = 'PY2'

TestExecutionBehavior = TestPlatformRequest.Params.TestExecutionBehavior

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'recipe_engine/time',
    'recipe_engine/uuid',
    'cros_resultdb',
    'cros_tags',
    'cros_test_runner',
    'cros_tool_runner',
    'cts_results_archive',
    'dut_interface',
    'phosphorus',
    'result_flow',
]

PROPERTIES = TestRunnerProperties
_DUMMY_TEST_ID = dut_interface.DUTTestMetadata.DUMMY_TEST_ID
_DUT_STATE_NEEDS_REPAIR = 'needs_repair'
_DUT_STATE_READY = 'ready'
_24_HOURS = 24 * 60 * 60

TAST_MISSING_TEST_KEY = 'tast_missing_test'


# API STEP HELPERS
def s_log(step, name, log):
  """Add a `log` to a `step`'s log under `name` is it exists.

  Args:
  * step (StepPresentation): The step to add this log under.
  * name (str): Log name.
  * log (Any): Object to add to log.
  """
  if log:
    step.presentation.logs[name] = log


def s_link(step, name, link):
  """Add a link `link` named `link_name` to the `step` if it exists.

  Args:
  * step (StepPresentation): The step to add this link under.
  * name (str): Link name.
  * link (str): Like URI to add.
  """
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
  with api.step.nest(step_name) as step:
    log = None
    if failure_condition:
      step.presentation.status = api.step.FAILURE
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
      raise StepFailure("Test name must be specified")


def archive_all_logs(api, interface, test_metadata, result):
  """Archive all test logs to Google Storage, updating result in the process.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe api.
    * interface (DUTInterface): The interface to run commands on the DUT.
    * test_metadata (DUTTestMetadata): All metadata needed for the interface
    apposite a test.
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
  with api.step.nest('test results') as step:
    if result.get_stainless_log_url():
      s_link(step=step, name='Autotest logs',
             link=result.get_stainless_log_url())
      s_log(step=step, name='JSON output', log=result.to_json())
    for prejob in result.get_prejob_steps():
      _set_step_status(
          api=api, step_name=prejob.name, summary=prejob.human_readable_summary,
          failure_condition=prejob.verdict != Result.Prejob.Step.VERDICT_PASS)
    for test_id, autotest_result in result.get_test_results():
      with api.step.nest(test_id):
        for test_case in autotest_result.test_cases:
          _set_step_status(
              api=api, step_name=test_case.name,
              summary=test_case.human_readable_summary,
              failure_condition=test_case.verdict !=
              Result.Autotest.TestCase.VERDICT_PASS)
      if result.is_test_incomplete():
        _set_step_status(api=api, step_name="autoserv",
                         summary=error_messages.AUTOSERV_CRASH)
    if not result.is_failure():
      if result.prejob_response.is_failure():
        _set_step_status(
            api=api, step_name="prejob execution",
            summary=error_messages.UNSUCCESSFUL_STATE.format(
                result.prejob_response.get_state_name()))
      for failed_test in result.get_failed_tests():
        _set_step_status(
            api=api,
            step_name="test execution for test: {}".format(failed_test.test_id),
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
      step.properties['compressed_result'] = result.serialize()


def _collect_tests_for_phosphorus(request):
  """Collects tests from Request into one dictionary

    Args:
    * request (Request): skylab_test_runner request instance.

    Returns: dictionary of skylab_test_runner.Request.Test instances
    """
  tests = {i: t for (i, t) in request.tests.items()}
  if request.HasField('test'):
    tests[_DUMMY_TEST_ID] = request.test
  return tests


def _generate_resultdb_base_tags(api):
  """Generate the base tags for the test results.

  Args:
    api (RecipeScriptApi): Ubiquitous recipe api.

  Returns:
    base_tags (dict): Tags for the test results.
  """
  base_tags = []

  drone = None
  for dimension in api.buildbucket.build.infra.swarming.bot_dimensions:
    if dimension.key == 'drone':
      drone = dimension.value
      base_tags.append(('drone', drone))
      break

  return base_tags


def _generate_resultdb_variant_def(api, request):
  """Generate the variant defintions for the test results.

    Args:
      api (RecipeScriptApi): Ubiquitous recipe api.
      request (Request): The test Request that the results belong to.

    Returns:
      base_variant (dict): Variant attributes for the test results.
    """
  base_variant = {}

  board = api.cros_tags.get_values('label-board')
  if board:
    base_variant['board'] = board[0]

  model = api.cros_tags.get_values('label-model')
  if model:
    base_variant['model'] = model[0]

  build_target = request.prejob.software_attributes.build_target.name
  if build_target:
    base_variant['build_target'] = build_target

  # The template of a parent_request_uid is
  # "TestPlanRuns/{ctp buildbucket id}/{tagged_request key}" where the
  # tagged_request key is the test config's display_name in
  # the GenerateTestPlanResponse. See http://shortn/_oPSae8w6Xc for more info.
  test_config_display_name = (
      request.parent_request_uid.split('/')[-1]
      if request.parent_request_uid else '')
  base_variant['test_config'] = test_config_display_name

  return base_variant


def _upload_missing_tast_results(api, base_dir, base_variant):
  """Upload test results for missing Tast test cases to ResultDB.

    Args:
      base_dir (string): The path of the base test results on the drone server.
      base_variant (dict): Variant key-value pairs to attach to the test
            results.
    """
  keyval_file = os.path.join(base_dir, 'autoserv_test', 'keyval')
  try:
    content = api.file.read_text('read keyval file', keyval_file,
                                 test_data='').splitlines()
  except api.file.Error:
    content = []
  missing_tests = []
  for line in content:
    if line.startswith(TAST_MISSING_TEST_KEY):
      test = line.split('=')[-1]
      missing_tests.append(test)
  api.cros_resultdb.report_missing_test_cases(missing_tests, base_variant)


def _upload_to_resultdb(api, result, properties, interface, test_metadata):
  """Upload test results to ResultDB.

    Args:
      api (RecipeScriptApi): Ubiquitous recipe api.
      result (DUTResult): The results of the test.
      properties (TestRunnerProperties): Recipe input properties.
      interface (DUTInterface): The interface to run commands on the DUT.
      test_metadata (DUTTestMetadata): All metadata needed for the interface
          apposite a test.
    """
  if not api.resultdb.enabled:
    return

  # Don't try to upload if there are no results.
  if not result:
    return

  base_dir = interface.get_results_directory(test_metadata)

  # TODO(b/200703493): Reconcile Chromium and CrOS test uploads in CTP2.
  if (test_metadata.test.autotest.test_args and
      'resultdb_settings' in test_metadata.test.autotest.test_args):
    config = api.cros_resultdb.extract_chromium_resultdb_settings(
        test_metadata.test.autotest.test_args)
    result_format = config.get('result_format')
    artifact_directory = config.get('artifact_directory')
    if result_format in {'tast', 'gtest'}:
      config['result_file'] = api.cros_resultdb.get_drone_result_file(
          base_dir, result_format)
      config[
          'artifact_directory'] = api.cros_resultdb.get_drone_artifact_directory(
              base_dir, result_format, artifact_directory)
    return api.cros_resultdb.upload(
        config, step_name='upload chromium test results to rdb')

  tast_results_dir = os.path.join(base_dir, 'autoserv_test/tast')
  if os.path.exists(tast_results_dir) or api.properties.get(
      'result_format') == 'tast':
    result_format = 'tast'
    result_file = api.cros_resultdb.get_drone_result_file(base_dir, 'tast')
    artifact_directory = api.cros_resultdb.get_drone_artifact_directory(
        base_dir, result_format)
  else:
    # Write the result to a file which can be read by result_adapter.
    temp_dir = api.path.mkdtemp()
    test_runner_result_file = temp_dir.join('test_runner_result.json')
    api.file.write_proto('write skylab_test_runner result',
                         test_runner_result_file, result.data, 'JSONPB')
    result_format = 'skylab-test-runner'
    result_file = test_runner_result_file
    artifact_directory = None

  config = {
      'result_format': result_format,
      'base_variant': _generate_resultdb_variant_def(api, properties.request),
      'base_tags': _generate_resultdb_base_tags(api),
      'result_file': result_file,
      'artifact_directory': artifact_directory,
  }

  api.cros_resultdb.upload(config, str(result.get_stainless_log_url()))
  _upload_missing_tast_results(api, base_dir, config.get('base_variant'))
  api.cros_resultdb.apply_exonerations(
      [api.cros_resultdb.current_invocation_id],
      properties.request.default_test_execution_behavior)


def _execution_steps_for_test_with_phosphorus(api, properties, interface,
                                              test_metadata, max_duration_sec,
                                              dut_state, container_image_info):
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
  apposite a test.
  * max_duration_sec (int): Maximum amount of time the job should run.
  * dut_state (str): The current state of the DUT.
  * container_image_info (ContainerImageInfo): If set, info on a Docker
  container for use by the DUTInterface.

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

      interface.upload_to_tko(test_metadata, run_test_response)

    result = interface.parse_test_results(test_metadata)
    result.add_prejob_response(prejob_response)
    result.add_test_response(run_test_response)
    if not prejob_response.is_failure():
      dut_state = result.get_dut_state()
  finally:
    # Must complete synchronous logs upload before sealing the results
    # directory. Once the results directory is sealed, gs_offloader may delete
    # the result files.
    archive_all_logs(api, interface=interface, test_metadata=test_metadata,
                     result=result)

    _upload_to_resultdb(api, result, properties, interface, test_metadata)

    api.cts_results_archive.archive(
        interface.get_results_directory(test_metadata))

    interface.save_and_seal_skylab_local_state(dut_state, test_metadata)

    publish_to_result_flow(api, properties.config,
                           properties.request.parent_request_uid,
                           should_poll_for_completion=True)
  set_output_properties(api, result=result)

  return result


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
        step.presentation.step_summary_text = 'Skipped: Build ID not set'
        return
      if not config.result_flow_pubsub.topic:
        step.presentation.step_summary_text = 'Skipped: PubSub topic not set'
        return
      if not config.result_flow_pubsub.project:
        step.presentation.step_summary_text = 'Skipped: PubSub project not set'
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
      with api.step.nest(test_id):
        validate_request(api, test)
        test_metadata = interface.build_test_metadata(test_id, test)
        # Needs to be distinct per test as logs are uploaded for each test separately.
        interface.save_skylab_local_state(_DUT_STATE_NEEDS_REPAIR,
                                          test_metadata)

        dut_state = _DUT_STATE_NEEDS_REPAIR
        max_duration_sec = (
            properties.config.harness.prejob_deadline_seconds or _24_HOURS)

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
    s_log(step, 'cft_mvp_test_request',
          json_format.MessageToJson(properties.cft_mvp_test_request))
    s_log(step, 'container_metadata',
          json_format.MessageToJson(api.cros_tool_runner.container_metadata))
    if properties.cft_mvp_test_request.parent_build_id:
      s_link(
          step=step, name='parent CTP', link=api.buildbucket.build_url(
              build_id=properties.cft_mvp_test_request.parent_build_id))

  with api.step.nest('inputs validation') as step:
    _validate_inputs_for_ctr(api, properties)

  with api.step.nest('execution steps') as step:
    publish_to_result_flow(api, properties.config,
                           properties.cft_mvp_test_request.parent_request_uid)
    test_metadata = interface.build_test_metadata(
        "original_test", "", properties.cft_mvp_test_request.autotest_keyvals)

    interface.save_skylab_local_state(_DUT_STATE_NEEDS_REPAIR, test_metadata)

    dut_state = _DUT_STATE_NEEDS_REPAIR
    max_duration_sec = (
        properties.config.harness.prejob_deadline_seconds or _24_HOURS)

    if interface.is_within_deadline():
      result = _execution_steps_for_test_with_ctr(
          api=api, properties=properties, interface=interface,
          test_metadata=test_metadata, max_duration_sec=max_duration_sec,
          dut_state=dut_state, container_image_info=None)
      global_result.add_result("original_test", result)
    else:
      prejob_response = interface.build_aborted_prejob_response(test_metadata)
      result = interface.parse_test_results(test_metadata)
      result.add_prejob_response(prejob_response)
      global_result.add_result("original_test", result)

  return global_result


def _execution_steps_for_test_with_ctr(api, properties, interface,
                                       test_metadata, max_duration_sec,
                                       dut_state, container_image_info):
  """Execute all the required steps for a single test using ctr.

  Run the following steps required for a test:
      * Run provision (prepare machine)
      * Run test

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * properties (TestRunnerProperties): recipe input properties.
  * interface (DUTInterface): The interface to run commands on the DUT.
  * test_metadata (DUTTestMetadata): All metadata needed for the interface
  apposite a test.
  * max_duration_sec (int): Maximum amount of time the job should run.
  * dut_state (str): The current state of the DUT.
  * container_image_info (ContainerImageInfo): If set, info on a Docker
  container for use by the DUTInterface.

  Returns: DUTResult: a constructed result for this test.

  Raises:
  * InfraFailure.
  """
  result = None
  run_test_response = None

  try:
    prejob_response = interface.submit_pre_job(test_metadata, max_duration_sec)
    if not prejob_response.any_provision_failed:
      run_test_response = interface.run_test(test_metadata,
                                             container_image_info)
      test_metadata.job_finished = int(api.time.time())
      dut_state = _DUT_STATE_READY
      interface.upload_to_tko(test_metadata, run_test_response)

    result = interface.parse_test_results(test_metadata)
    result.add_prejob_response(prejob_response)
    result.add_test_response(run_test_response)
  finally:
    archive_all_logs(api, interface=interface, test_metadata=test_metadata,
                     result=result)
    interface.save_and_seal_skylab_local_state(dut_state, test_metadata)

    publish_to_result_flow(api, properties.config,
                           properties.cft_mvp_test_request.parent_request_uid,
                           should_poll_for_completion=True)

  return result


def summarize_results_from_ctr_results(api, result):
  """Display test cases (and failures) as recipe substeps through the api.

    Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
      * result (DUTResult): The result of all tests.
    """
  with api.step.nest('test results') as step:
    if result.get_stainless_log_url():
      s_link(step=step, name='Autotest logs',
             link=result.get_stainless_log_url())
    for prejob in result.get_prejob_steps():
      _set_step_status(api=api, step_name="provision of " + prejob.test_id,
                       summary="", failure_condition=prejob.is_failure())
    for test_result in result.get_test_results():
      _set_step_status(api=api, step_name=test_result.test_id, summary="",
                       failure_condition=test_result.is_failure())


def _validate_inputs_for_ctr(api, properties):
  """Validate inputs for CTR.

    Args:
      * api (RecipeScriptApi): Ubiquitous recipe api.
      * properties (TestRunnerProperties): recipe input properties.
    """
  _validate_proto_field(api, properties, 'cft_mvp_test_request', True)
  _validate_proto_field(api, properties.cft_mvp_test_request, 'primary_dut',
                        True)
  _set_step_status(
      api=api, step_name='container_metadata_key validation',
      summary='container_metadata_key is missing',
      failure_condition=not properties.cft_mvp_test_request.primary_dut
      .container_metadata_key, fail_build=True)
  _set_step_status(
      api=api, step_name='test_suites validation',
      summary='test_suites is missing',
      failure_condition=not properties.cft_mvp_test_request.test_suites,
      fail_build=True)


def RunSteps(api, properties):
  if api.cros_test_runner.is_enabled():  # pragma: nocover
    # Experimental code path for using the new test_runner binary rather
    # than the normal test_runner workflow.
    api.cros_test_runner.execute_luciexe()
    return
  if properties.cft_mvp_is_enabled:
    result = execution_steps_with_ctr(api, properties)
    summarize_results_from_ctr_results(api, result)
  else:
    result = execution_steps_with_phosphorus(api, properties)
    summarize_results_from_phosphorus_results(api, result)

  if result.has_any_failures():
    with api.step.nest('build status'):
      if result.test_failed():
        raise api.step.StepFailure('test failed')
      if result.prejob_failed():
        raise api.step.StepFailure('prejob failed')
      raise api.step.StepFailure('prejob or test failed')


def GenTests(api):

  def _set_build(bid, tags=None, experiments=None, swarming_tags=None):
    # tags is a dict, convert that into [StringPair].
    bb_tags = api.cros_tags.tags(**tags) if tags else []
    build_msg = api.buildbucket.ci_build_message(build_id=bid, tags=bb_tags,
                                                 experiments=experiments,
                                                 project='chromeos',
                                                 bucket='test_runner',
                                                 builder='test_runner')
    if swarming_tags:
      build_msg.infra.swarming.bot_dimensions.extend(
          api.cros_tags.tags(**swarming_tags))
    return api.buildbucket.build(build_msg)

  def _build_with_execution_timeout(timeout_s):
    # NB: The input Build does not have start_time set, because buildbucket has
    # no way of knowing when the swarming task for the build will start.
    return build_pb2.Build(
        id=22,
        execution_timeout=duration_pb2.Duration(seconds=timeout_s),
    )

  def _keyval_file_step_data():
    return api.step_data(
        'execution steps.original_test.read keyval file',
        api.file.read_text("""
parent_job_id=58067d9ab42aca11
build=board-cq/R00-0.0.0
suite=sweet-cq
synchronous_log_data_stainless_url=https://path/to/stainless
synchronous_log_data_url=gs://path/to/test/logs
label=board-cq/R00-0.0.0/sweet-cq/test-case
drone=skylab-drone-xyz
hostname=chromeos0-row0-rack0-host0
job_started=0
status_version=0
user=test-user
tast_missing_test.0=foo.SomeTest
tast_missing_test.1=foo.SomeOtherTest
tast_missing_test.2=bar.DifferentTest
tast_missing_test.3=bar.YetAnotherTest
    """))

  # Required for initial module set up.
  def _misc_properties(cft_mvp_is_enabled=False):
    if cft_mvp_is_enabled:
      return _misc_properties_for_ctr()
    else:
      return _misc_properties_for_phosphorus()

  def _misc_properties_for_ctr():
    return (api.properties(
        _get_test_runner_properties(), **{
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
                        cipd_label='cros_tool_runner_prod'),
                    container_metadata=mock_metadata())
        }) + api.properties.environ(
            PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                    SWARMING_TASK_ID='dummy-task-id',
                                    SKYLAB_DUT_ID='dummy-dut-id')) +
            api.properties.environ(
                CrosToolRunnerEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                            SWARMING_TASK_ID='dummy-task-id',
                                            SKYLAB_DUT_ID='dummy-dut-id')))

  def _get_test_runner_properties():
    return TestRunnerProperties(
        config={
            'lab': {
                'admin_service': 'foo-service',
                'cros_inventory_service': 'inv-service',
                'cros_ufs_service': 'ufs-service'
            },
            'harness': {
                'autotest_dir': '/path/to/autotest',
                'prejob_deadline_seconds': 60 * 60,
            },
            'output': {
                'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
            },
            'result_flow_pubsub': {
                'project': 'foo-proj',
                'topic': 'foo-topic',
            },
        })

  def _misc_properties_for_phosphorus():
    return (api.properties(
        _get_test_runner_properties(), **{
            '$chromeos/phosphorus':
                PhosphorusProperties(
                    version=PhosphorusProperties.Version(
                        cipd_label='phosphorus_prod'), config={
                            'admin_service': 'foo-service',
                            'cros_inventory_service': 'inv-service',
                            'cros_ufs_service': 'ufs-service',
                            'autotest_dir': '/path/to/autotest',
                        })
        }) +  #
            api.properties.environ(
                PhosphorusEnvProperties(SWARMING_BOT_ID='crossk-dummy',
                                        SWARMING_TASK_ID='dummy-task-id',
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
  def _request_properties_with_test_exec_behavior(default_behavior):
    return (api.properties(
        TestRunnerProperties(
            request=_canned_test_runner_request(
                default_behavior=default_behavior))))

  def _request_properties_with_suite_name(suite_name):
    request = _canned_test_runner_request()
    request['test']['autotest']['keyvals']['suite'] = suite_name
    return api.properties(TestRunnerProperties(request=request))

  def _canned_test_runner_request(
      test_arg='foo=bar',
      default_behavior=TestExecutionBehavior.BEHAVIOR_UNSPECIFIED):
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
            'software_dependencies': [{
                'chromeos_build': 'fake_build',
            },]
        },
        'test': {
            'autotest': {
                'name': 'dummy_name',
                'test_args': test_arg,
                'keyvals': {
                    'key1': 'value1',
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
            'software_dependencies': [{
                'chromeos_build': 'fake_build',
            },]
        },
        'tests': {
            'multi_test_2':
                Request.Test(
                    autotest={
                        'name': 'dummy_name',
                        'test_args': 'foo=bar',
                        'keyvals': {
                            'key1': 'val1'
                        },
                        'is_client_test': True,
                        'display_name': 'multi_test_2'
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
            'software_dependencies': [{
                'chromeos_build': 'fake_build',
            },],
            'secondary_devices': [{
                'software_attributes': {
                    'build_target': {
                        'name': 'fake_board2',
                    }
                },
                'software_dependencies': [{
                    'chromeos_build': 'fake_build2',
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
            'software_dependencies': [{
                'chromeos_build': 'fake_build',
            },],
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
                skylab_local_state.load.LoadResponse(
                    results_dir='dummy-results-dir', dut_topology=[
                        skylab_local_state.load.Dut(hostname='fake_host',
                                                    board='fake_board',
                                                    model='fake_model'),
                    ])))))

  def _successful_prejob_step(test_id=_DUMMY_TEST_ID):
    return _prejob_step_with_state(phosphorus.prejob.PrejobResponse.SUCCEEDED,
                                   test_id)

  def _prejob_step_with_state(state, test_id=_DUMMY_TEST_ID):
    return (api.step_data(
        'execution steps.%s.Phosphorus: run prejob.call `phosphorus`.prejob' %
        test_id, stdout=api.raw_io.output(
            json_format.MessageToJson(
                phosphorus.prejob.PrejobResponse(state=state)))))

  def _successful_run_test_step():
    return _run_test_step_with_state(
        phosphorus.runtest.RunTestResponse.SUCCEEDED)

  def _run_test_step_with_state(state, test_id=_DUMMY_TEST_ID):
    return (api.step_data(
        'execution steps.%s.Phosphorus: run test.call `phosphorus`.run-test' %
        test_id, stdout=api.raw_io.output(
            json_format.MessageToJson(
                phosphorus.runtest.RunTestResponse(
                    results_dir='dummy-results-dir/subdir', state=state)))))

  def _successful_fetch_crashes_step(test_id=_DUMMY_TEST_ID):
    return _fetch_crashes_step_with_state(
        phosphorus.fetchcrashes.FetchCrashesResponse.SUCCEEDED, test_id)

  def _fetch_crashes_step_with_state(state, test_id=_DUMMY_TEST_ID):
    return _fetch_crashes_step_with_proto(
        phosphorus.fetchcrashes.FetchCrashesResponse(state=state), test_id)

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
                phosphorus.upload_to_gs.UploadToGSResponse(
                    gs_url='gs://chromeos-test-logs/common-env/UUID/logs'))))

  ######## CFT MVP Testing related functions ############

  def mock_metadata(target="test-target"):
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
  def _request_properties_for_ctr(cft_mvp_test_request=None):
    if not cft_mvp_test_request:
      cft_mvp_test_request = _canned_test_runner_request_for_ctr()
    return (api.properties(
        TestRunnerProperties(cft_mvp_is_enabled=True,
                             cft_mvp_test_request=cft_mvp_test_request)))

  def _canned_test_runner_request_for_ctr():
    return {
        "parent_build_id":
            12345,
        "primary_dut": {
            "container_metadata_key": "kevin",
            "dut_model": {
                "build_target": "kevin",
                "model_name": "kevin"
            }
        },
        "test_suites": [{
            "name": "suite1",
            "test_case_ids": {
                "test_case_ids": [{
                    "value": "tauto.stub_Pass"
                }, {
                    "value": "tast.example.Fail"
                }, {
                    "value": "tast.example.Pass"
                }]
            }
        }]
    }

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
                skylab_local_state.load.LoadResponse(
                    results_dir='dummy-results-dir', dut_topology=[
                        skylab_local_state.load.Dut(hostname='fake_host',
                                                    board='fake_board',
                                                    model='fake_model'),
                    ], lab_dut_topology=[
                        lab_api.dut.DutTopology(
                            id=lab_api.dut.DutTopology.Id(value="fake_host"),
                            duts=[
                                lab_api.dut.Dut(
                                    id=lab_api.dut.Dut.Id(value="fake_host"),
                                    cache_server=lab_api.dut.CacheServer(
                                        address=IpEndpoint(
                                            address="0.0.0.0", port=123)),
                                    chromeos=lab_api.dut.Dut.ChromeOS(
                                        dut_model=lab_api.dut.DutModel(
                                            build_target="fake_board",
                                            model_name="fake_model"),
                                        ssh=IpEndpoint(address="fake_host",
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
                ctr_api.cros_tool_runner_cli.CrosToolRunnerProvisionResponse(
                    responses=[
                        _provision_resp_with_state_for_ctr(
                            state=state, failure_reason=failure_reason)
                    ])))))

  def _provision_resp_with_state_for_ctr(state, failure_reason=None):
    provision_resp = ctr_api.cros_provision_cli.CrosProvisionResponse(
        id=lab_api.dut.Dut.Id(value="test_dut_host_name"))
    data = {state: {}}
    if state == 'failure' and failure_reason:
      data['failure']['reason'] = failure_reason

    return json_format.ParseDict(data, provision_resp)

  def _successful_run_test_step_for_ctr():
    return _run_test_step_with_state_for_ctr('pass')

  def _failed_run_test_step_for_ctr():
    return _run_test_step_with_state_for_ctr('fail')

  def _run_test_step_with_state_for_ctr(state):
    return (api.step_data(
        'execution steps.CrosToolRunner: run test.call `cros-tool-runner`.test',
        stdout=api.raw_io.output(
            json_format.MessageToJson(
                ctr_api.cros_tool_runner_cli.CrosToolRunnerTestResponse(
                    test_case_results=[
                        _test_case_result_resp_with_state_for_ctr(state=state)
                    ])))))

  def _test_case_result_resp_with_state_for_ctr(state):
    test_case_result = ctr_api.test_case_result.TestCaseResult(
        test_case_id=ctr_api.test_case.TestCase.Id(value="dummy_id"),
        result_dir_path=StoragePath(host_type=StoragePath.HostType.LOCAL,
                                    path="dummy-results-dir/subdir"))
    data = {state: {}}
    return json_format.ParseDict(data, test_case_result)

  ########## Test cases #########

  yield api.test(
      'test_name_missing',
      _misc_properties(),
      _request_properties_no_name(),
      api.post_check(post_process.StatusFailure),
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
  )

  yield api.test(
      'no-tast-keyval-file',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45'
          }, swarming_tags={'drone': 'fake-drone-1234'}),
      api.step_data('execution steps.original_test.read keyval file',
                    api.file.read_text(errno_name='file does not exist')),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'success-with-resultdb-tast',
      _set_build(
          bid=42, tags={
              'label-board': 'fake-board',
              'label-model': 'fake-model',
              'build': 'fake-board-cq/R11-123.45'
          }, swarming_tags={'drone': 'fake-drone-1234'}),
      _keyval_file_step_data(),
      api.properties(result_format='tast'),
      _misc_properties(),
      _request_properties_with_test_exec_behavior(
          TestExecutionBehavior.NON_CRITICAL),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'success_multi_duts',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_multiduts(),
      api.step_data(
          'execution steps.original_test.Phosphorus: load skylab local state.'
          'call `phosphorus`.load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  skylab_local_state.load.LoadResponse(
                      results_dir='dummy-results-dir', dut_topology=[
                          skylab_local_state.load.Dut(hostname='fake_hostname',
                                                      board='fake_board',
                                                      model='fake_model'),
                          skylab_local_state.load.Dut(hostname='fake_hostname2',
                                                      board='fake_board2',
                                                      model='fake_model2')
                      ])))),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'success_multi_duts_with_android_devices',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_multiduts_with_androids(),
      api.step_data(
          'execution steps.original_test.Phosphorus: load skylab local state.'
          'call `phosphorus`.load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  skylab_local_state.load.LoadResponse(
                      results_dir='dummy-results-dir', dut_topology=[
                          skylab_local_state.load.Dut(hostname='fake_hostname',
                                                      board='fake_board',
                                                      model='fake_model'),
                          skylab_local_state.load.Dut(
                              hostname='fake_hostname2',
                              board='fake_android_board',
                              model='fake_android_model')
                      ])))),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  r_with_deadline = _canned_test_runner_request()
  r_with_passed_deadline = _canned_test_runner_request()
  current_time_sec = 2369692800
  test_deadline = timestamp_pb2.Timestamp(seconds=current_time_sec - 100)
  r_with_deadline['deadline'] = timestamp_pb2.Timestamp(
      seconds=current_time_sec + 55)
  r_with_passed_deadline['deadline'] = test_deadline

  yield api.test(
      'deadline_passed',
      api.time.seed(current_time_sec),
      _misc_properties(),
      api.properties(TestRunnerProperties(request=r_with_passed_deadline)),
      _mock_load_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'success_with_build_deadline',
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
      'success_with_request_deadline',
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
      'prejob_crash',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: run prejob.call '
          '`phosphorus`.prejob', retcode=1),
  )

  yield api.test(
      'run_test_crash',
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: run test.call '
          '`phosphorus`.run-test', retcode=1),
  )

  yield api.test(
      'upload_to_tko_crash',
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: upload to TKO.call '
          '`phosphorus`.upload-to-tko', retcode=1),
  )

  yield api.test(
      'mismatched_test_result_directory',
      _misc_properties(),
      _request_properties(),
      api.step_data(
          'execution steps.original_test.Phosphorus: load skylab local state.'
          'call `phosphorus`.load', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  skylab_local_state.load.LoadResponse(
                      results_dir='dummy-results-dir', dut_topology=[
                          skylab_local_state.load.Dut(hostname="fake_hostname",
                                                      board="fake_board",
                                                      model="fake_model")
                      ])))),
      _successful_prejob_step(),
      api.step_data(
          'execution steps.original_test.Phosphorus: run test.call `phosphorus`'
          '.run-test', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  phosphorus.runtest.RunTestResponse(
                      results_dir='not-a-subdir-of-dummy-results-dir',
                      state=phosphorus.runtest.RunTestResponse.SUCCEEDED)))),
  )

  yield api.test(
      'link_to_all_archived_logs',
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
      'get_results_crash',
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
  )

  yield api.test(
      'results_summary',
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
  )

  yield api.test(
      'failed_prejob_with_missing_failures_in_result',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _prejob_step_with_state(phosphorus.prejob.PrejobResponse.FAILED),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'failed_run-test_with_missing_failures_in_result',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _run_test_step_with_state(phosphorus.runtest.RunTestResponse.FAILED),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'successful_run-test_with_multiple_tests',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_multitest(),
      _mock_load_step(test_id='multi_test_2'),
      _successful_prejob_step(test_id='multi_test_2'),
      _run_test_step_with_state(phosphorus.runtest.RunTestResponse.SUCCEEDED,
                                test_id='multi_test_2'),
      _successful_fetch_crashes_step(test_id='multi_test_2'),
      _successful_logs_archive_step(test_id='multi_test_2'),
  )

  yield api.test(
      'failed_fetch-crashes',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _fetch_crashes_step_with_state(phosphorus.runtest.RunTestResponse.FAILED),
      _successful_logs_archive_step(),
  )

  fetch_crashes_proto = phosphorus.fetchcrashes.FetchCrashesResponse(
      state=phosphorus.runtest.RunTestResponse.SUCCEEDED,
      crashes_rtd_only=["foobar.meta"])
  yield api.test(
      'successful_fetch-crashes-with-missed-crashes',
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
      'skip_result_flow_pubsub_due_to_missing_build_ID',
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'skip_result_flow_pubsub_due_to_missing_topic',
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
      'skip_result_flow_pubsub_due_to_missing_project',
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

  rdb_settings = api.json.dumps({
      'result_format': 'tast',
      'base_tags': ['test_suite:lacros_all_tast_tests'],
      'base_variant': {
          'test_suite': 'lacros_all_tast_tests',
      },
  })
  yield api.test(
      'chromium_test_upload_result_to_rdb',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_rdb('resultdb_settings=%s' %
                              base64.b64encode(rdb_settings)),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      api.post_process(
          post_process.StepCommandContains,
          'execution steps.original_test.upload chromium test results '
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
          post_process.MustRun,
          'execution steps.original_test.upload chromium test results to rdb.'
          'run rdb'),
  )

  yield api.test(
      'chromium_test_upload_result_to_rdb_failure',
      _set_build(bid=42),
      _misc_properties(),
      _request_properties_rdb('resultdb_settings=%s' %
                              base64.b64encode(rdb_settings)),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
      api.step_data(
          'execution steps.original_test.upload chromium test results '
          'to rdb.run rdb', retcode=1),
      api.post_process(
          post_process.StepWarning, 'execution steps.'
          'original_test.upload chromium test results to rdb'),
      api.post_process(
          post_process.MustRun,
          'execution steps.Phosphorus: remove autotest results dir'),
  )

  yield api.test(
      'dut_topology_experiment_flag',
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
      'dut_topology_test_allowlist',
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
      'dut_topology_suite_allowlist',
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

  ############ CTR Test Cases ##########

  yield api.test('success_with_ctr', _set_build(bid=42), _misc_properties(True),
                 _request_properties_for_ctr(), _mock_load_step_for_ctr(),
                 _successful_prejob_step_for_ctr(),
                 _successful_run_test_step_for_ctr())

  yield api.test(
      'within_deadline_ctr', api.time.seed(2369692800), _misc_properties(True),
      _request_properties_for_ctr(
          cft_mvp_test_request=_canned_test_runner_request_for_ctr_within_deadline(
              current_time_sec=2369692800)), _mock_load_step_for_ctr(),
      _successful_prejob_step_for_ctr(), _successful_run_test_step_for_ctr())

  yield api.test(
      'deadline_passed_ctr', api.time.seed(2369692800), _misc_properties(True),
      _request_properties_for_ctr(
          cft_mvp_test_request=_canned_test_runner_request_for_ctr_passed_deadline(
              current_time_sec=2369692800)), _mock_load_step_for_ctr())

  yield api.test(
      'primary_dut_missing',
      _misc_properties(True),
      _request_properties_for_ctr(
          cft_mvp_test_request=_canned_test_runner_request_for_ctr_with_missing_field(
              missing_field_name='primary_dut')),
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'test_suites_missing',
      _misc_properties(True),
      _request_properties_for_ctr(
          cft_mvp_test_request=_canned_test_runner_request_for_ctr_with_missing_field(
              missing_field_name='test_suites')),
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'provision_crash_ctr', _set_build(bid=42), _misc_properties(True),
      _request_properties_for_ctr(), _mock_load_step_for_ctr(),
      api.step_data(
          'execution steps.CrosToolRunner: run provision.call `cros-tool-runner`.provision',
          retcode=1), api.post_check(post_process.StatusException))

  yield api.test(
      'run_test_crash_ctr', _misc_properties(True),
      _request_properties_for_ctr(), _mock_load_step_for_ctr(),
      _successful_prejob_step_for_ctr(),
      api.step_data(
          'execution steps.CrosToolRunner: run test.call `cros-tool-runner`.test',
          retcode=1), api.post_check(post_process.StatusFailure))

  yield api.test('provision_failed_ctr', _set_build(bid=42),
                 _misc_properties(True), _request_properties_for_ctr(),
                 _mock_load_step_for_ctr(), _failed_prejob_step_for_ctr(),
                 api.post_check(post_process.StatusFailure))

  yield api.test('test_failed_ctr', _set_build(bid=42), _misc_properties(True),
                 _request_properties_for_ctr(), _mock_load_step_for_ctr(),
                 _successful_prejob_step_for_ctr(),
                 _failed_run_test_step_for_ctr(),
                 api.post_check(post_process.StatusFailure))
