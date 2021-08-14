# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Skylab Test Runner."""
import base64

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder as builder_pb2
from PB.recipe_modules.chromeos.phosphorus.phosphorus \
  import PhosphorusProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus\
  import PhosphorusEnvProperties
from PB.recipes.chromeos.test_platform.test_runner import TestRunnerProperties
from PB.test_platform import phosphorus
from PB.test_platform import skylab_local_state
from PB.test_platform.skylab_test_runner.result import Result
from PB.test_platform.skylab_test_runner.request import Request

from google.protobuf import duration_pb2
from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.dut_interface import dut_interface, error_messages

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'recipe_engine/uuid',
    'cros_resultdb',
    'cros_tags',
    'cros_test_runner',
    'cts_results_archive',
    'dut_interface',
    'phosphorus',
    'result_flow',
]

PROPERTIES = TestRunnerProperties
_DUMMY_TEST_ID = dut_interface.DUTTestMetadata.DUMMY_TEST_ID
_DUT_STATE_NEEDS_REPAIR = 'needs_repair'
_24_HOURS = 24 * 60 * 60


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


def _set_step_status(api, step_name, summary, failure_condition=True):
  """Sets a status for an individual step.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * step_name (str): The name of the new step
  * summary (str): Information for the log.
  * failure_condition (bool): What constitutes a failure in this step.
  """
  with api.step.nest(step_name) as step:
    if failure_condition:
      step.presentation.status = api.step.FAILURE
    s_log(step=step, name='summary', log=summary)


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


def summarize_results(api, result):
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
    for test_id, autotest_result in result.get_autotest_results():
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


def _collect_tests(request):
  """Collects tests from Request into one dictionary

  Args:
  * request (Request): skylab_test_runner request instance.

  Returns: dictionary of skylab_test_runner.Request.Test instances
  """
  tests = {i: t for (i, t) in request.tests.items()}
  if request.HasField('test'):
    tests[_DUMMY_TEST_ID] = request.test
  return tests


def _execution_steps_for_test(api, properties, interface, test_metadata,
                              max_duration_sec, dut_state):
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
      run_test_response = interface.run_test(test_metadata)
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

    if (test_metadata.test.autotest.test_args and
        'resultdb_settings' in test_metadata.test.autotest.test_args):
      api.cros_resultdb.upload(api.buildbucket.builder_name,
                               test_metadata.test.autotest.test_args,
                               interface.get_results_directory(test_metadata))

    api.cts_results_archive.archive(
        interface.get_results_directory(test_metadata))

    interface.save_and_seal_skylab_local_state(dut_state, test_metadata)

    publish_to_result_flow(api, properties.config, properties.request,
                           should_poll_for_completion=True)
  set_output_properties(api, result=result)

  return result


def publish_to_result_flow(api, config, request,
                           should_poll_for_completion=False):
  """Publish build info to result_flow PubSub.

  Args:
  * api (RecipeScriptApi): Ubiquitous recipe api.
  * config (Config): Input test Config.
  * request (Request): Input test request.
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
          parent_uid=request.parent_request_uid)


def execution_steps(api, properties):
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
  tests = _collect_tests(properties.request)
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
    publish_to_result_flow(api, properties.config, properties.request)

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
          result = _execution_steps_for_test(api=api, properties=properties,
                                             interface=interface,
                                             test_metadata=test_metadata,
                                             max_duration_sec=max_duration_sec,
                                             dut_state=dut_state)
          global_result.add_result(test_id, result)
        else:
          prejob_response = interface.build_aborted_prejob_response(
              test_metadata)
          result = interface.parse_test_results(test_metadata)
          result.add_prejob_response(prejob_response)
          global_result.add_result(test_id, result)
          archive_all_logs(api, interface=interface,
                           test_metadata=test_metadata, result=result)

  return global_result


def RunSteps(api, properties):
  if api.cros_test_runner.is_enabled():  # pragma: nocover
    # Experimental code path for using the new test_runner binary rather
    # than the normal test_runner workflow.
    api.cros_test_runner.execute_luciexe()
    return
  result = execution_steps(api, properties)

  summarize_results(api, result)

  if result.has_any_failures():
    with api.step.nest('build status'):
      raise api.step.StepFailure('prejob or test failed')


def GenTests(api):
  _gs_root = "gs://bucket/foo/bar"
  _sync_subdir = "synchronous_subdir"

  def _set_build_id(bid, tags=None):
    # tags is a dict, convert that into [StringPair].
    bb_tags = api.cros_tags.tags(**tags) if tags else []
    return api.buildbucket.build(build_pb2.Build(id=bid, tags=bb_tags))

  def _build_with_execution_timeout(timeout_s):
    # NB: The input Build does not have start_time set, because buildbucket has
    # no way of knowing when the swarming task for the build will start.
    return build_pb2.Build(
        id=22,
        execution_timeout=duration_pb2.Duration(seconds=timeout_s),
    )

  # Required for initial module set up.
  def _misc_properties():
    return (api.properties(
        TestRunnerProperties(
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
            }), **{
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

  # An example request represents chromium tests which upload result
  # to rdb.
  def _request_properties_rdb(test_arg):
    return (api.properties(
        TestRunnerProperties(request=_canned_test_runner_request(test_arg))))

  def _canned_test_runner_request(test_arg='foo=bar'):
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

  yield api.test(
      'test_name_missing',
      _misc_properties(),
      _request_properties_no_name(),
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'success',
      _set_build_id(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_fetch_crashes_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'success_multi_duts',
      _set_build_id(bid=42),
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

  # yield api.test(
  #     'fetch_crashes_crash', _misc_properties(), _request_properties(),
  #     _mock_load_step(), _successful_prejob_step(), _successful_run_test_step(),
  #     api.step_data(
  #         'execution steps.original_test.fetch crashes.call `phosphorus`.fetch-crashes',
  #         retcode=1))

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
      _set_build_id(bid=42),
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
      _set_build_id(bid=42),
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
      _set_build_id(bid=42),
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
      _set_build_id(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _prejob_step_with_state(phosphorus.prejob.PrejobResponse.FAILED),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'failed_run-test_with_missing_failures_in_result',
      _set_build_id(bid=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _run_test_step_with_state(phosphorus.runtest.RunTestResponse.FAILED),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'successful_run-test_with_multiple_tests',
      _set_build_id(bid=42),
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
      _set_build_id(bid=42),
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
      _set_build_id(bid=42),
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
      _set_build_id(bid=42),
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
      _set_build_id(bid=42),
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
      'result_format': 'gtest',
      'artifact_directory': '/tmp/artifact',
      'result_file': 'output.json',
      'base_tags': ['test_suite:cast_shell_browsertests'],
      'base_variant': {
          'test_suite': 'cast_shell_browsertests',
      },
  })
  yield api.test(
      'chormium_test_upload_result_to_rdb',
      api.buildbucket.ci_build(),
      api.buildbucket.build(
          build_pb2.Build(
              id=42, builder=builder_pb2.BuilderID(
                  project='chromeos',
                  bucket='test_runner',
                  builder='test_runner',
              ), infra=build_pb2.BuildInfra(
                  resultdb=build_pb2.BuildInfra.ResultDB(
                      invocation='invocations/build:%d' % 42)))),
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
          'execution steps.original_test.upload chromium test result '
          'to rdb.run rdb',
          [
              '[START_DIR]/cipd/result_adapter/result_adapter',
              'gtest',
              '-result-file',
              'dummy-results-dir/autoserv_test/chromium/results/output.json',
          ],
      ),
      api.post_process(
          post_process.MustRun,
          'execution steps.original_test.upload chromium test result to rdb.'
          'run rdb'),
  )
