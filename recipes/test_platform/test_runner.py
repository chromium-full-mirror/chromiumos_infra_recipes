# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Skylab Test Runner."""

import os

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.phosphorus.phosphorus \
  import PhosphorusProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus \
  import PhosphorusEnvProperties
from PB.recipe_modules.chromeos.autotest_status_parser.autotest_status_parser \
  import AutotestStatusParserProperties
from PB.recipes.chromeos.test_platform.test_runner import \
  TestRunnerProperties
from PB.test_platform import phosphorus
from PB.test_platform import skylab_local_state
from PB.test_platform.skylab_test_runner.result import AsyncResults, Result
from PB.test_platform.skylab_test_runner.request import Request

from google.protobuf import duration_pb2
from google.protobuf import json_format
from google.protobuf import timestamp_pb2
from posixpath import join as url_join

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'recipe_engine/uuid',
    'autotest_status_parser',
    'cros_tags',
    'phosphorus',
    'result_flow',
]

PROPERTIES = TestRunnerProperties


def validate_request(api, test):
  """Validate the TestRunnerProperties.

  Args:
    * test: skylab_test_runner.Request.Test instance.

  Raises:
    * ValueError if there are invalid properties.
  """
  with api.step.nest('validate request'):
    if not test.autotest.name:
      raise ValueError("Test name must be specified")


def prejob(api, config=None, request=None, dut_hostname='', load_response=None,
           max_duration_seconds=None):
  """Run a prejob (e.g. provision) against the DUT via `autoserv`.

  Args:
    * config: phosphorus.Config instance.
    * request: skylab_test_runner.Request instance.
    * dut_hostname: DUT hostname string.
    * load_response: LoadStateResponse instance.
    * max_duration_seconds: int.

  Returns:
    * phosphorus.prejob.PrejobResponse

  Raises:
    * InfraFailure if prejob fails.
  """
  with api.step.nest('run prejob') as step:
    with api.context(infra_steps=True):
      prejob_request = phosphorus.prejob.PrejobRequest(
          config=config,
          dut_hostname=dut_hostname,
          desired_provisionable_labels=request.prejob.provisionable_labels,
          existing_provisionable_labels=load_response.provisionable_labels,
          use_tls=request.prejob.use_tls,
      )
      # Use the earlier of the two deadlines: the globally configured max
      # duration or the request's deadline (if provided).
      prejob_request.deadline.seconds = (
          api.time.ms_since_epoch() / 1000 + max_duration_seconds)
      deadline = _deadline(api, request)
      if deadline.seconds < prejob_request.deadline.seconds:
        prejob_request.deadline.MergeFrom(deadline)
      return api.phosphorus.prejob(prejob_request)


def run_test(api, config=None, request=None, output_config=None,
             dut_hostname='', test=None, logs_gs_dir=''):
  """Run a test against the DUT via `autoserv`.

  Args:
    * config: phosphorus.Config instance.
    * request: skylab_test_runner.Request instance.
    * output_config: skylab_test_runner.Config.Output instance.
    * dut_hostname: DUT hostname string.
    * test: skylab_test_runner.Request.Test instance.
    * logs_gs_dir: The Google Storage directory where test logs will be uploaded.

  Returns:
    * phosphorus.runtest.RunTestResponse

  Raises:
    * StepFailure if test crashes.
      (No exception is raised if test fails without a crash.)
  """
  with api.step.nest('run test') as step:
    run_test_request = phosphorus.runtest.RunTestRequest(
        config=config,
        dut_hostnames=[dut_hostname],
        autotest=phosphorus.runtest.RunTestRequest.Autotest(
            name=test.autotest.name,
            test_args=test.autotest.test_args,
            display_name=test.autotest.display_name,
            keyvals=_with_gs_logs_keyval(test.autotest.keyvals, logs_gs_dir),
            is_client_test=test.autotest.is_client_test,
        ),
        environment=phosphorus.runtest.RunTestRequest.Environment(
            gs_root_dir=output_config.gs_root_dir),
    )
    deadline = _deadline(api, request)
    run_test_request.deadline.MergeFrom(deadline)
    return api.phosphorus.run_test(run_test_request)


def _with_gs_logs_keyval(keyvals, logs_gs_dir):
  # This keyval is required for stainless' test results view to link to the
  # test logs.
  # - Autoserv drops keyvals in a file in the logs directory
  # - tko/parse parses that file and injects keyvals in the TKO database
  # - Stainless table builder extracts this particular keyval and uses the value
  #   to link to the archived logs.
  keyvals['synchronous_log_data_url'] = logs_gs_dir
  keyvals['synchronous_log_data_stainless_url'] = _stainless_logs_from_gs_path(
      logs_gs_dir)
  return keyvals


def _deadline(api, request):
  """Determine the deadline for this build.

  Args:
    request: skylab_test_runner.Request instance.

  Returns:
    google.protobuf.Timestamp instance.
  """
  build_deadline = _build_deadline(api)
  # Must explicitly check for existence of deadline.
  # Reading the deadline from a request where the field is unset returns
  # the zero value. The zero value google.protobuf.Timestamp translates to
  # a non-zero time.Time in Go.
  if not request.HasField('deadline'):
    return build_deadline
  if build_deadline.seconds < request.deadline.seconds:
    return build_deadline
  return request.deadline


def _build_deadline(api):
  """Determine the deadline for this buildbucket build."""
  build_timeout = api.buildbucket.build.execution_timeout
  # Ideally, we'd want to calculate using the start_time of the build.
  # But the input Build does not have start_time set, so we use the current time
  # as a proxy. This assumes that not too much time has elapsed from the start
  # of the build till this point.
  now_seconds = api.time.ms_since_epoch() / 1000
  return timestamp_pb2.Timestamp(seconds=now_seconds + build_timeout.seconds)


def archive_all_logs(api, phosphorus_config, gs_dir, result):
  """Archive all test logs to Google Storage.

  Args:
    * phosphorus_config: phosphorus.Config instance
    * gs_dir: str, path to Google Storage directory to archive to.
    * result: test_runner.Result.
  Returns:
    Updated test_runner.Result
  Raises:
    * InfraFailure if binary call fails.
  """
  with api.context(infra_steps=True):
    with api.step.nest('archive all test logs to Google Storage'):
      gs_res = api.phosphorus.upload_to_gs(
          phosphorus.upload_to_gs.UploadToGSRequest(
              config=phosphorus_config,
              local_directory=phosphorus_config.task.results_dir,
              gs_directory=gs_dir,
          ))
      # Logs are archived even in the case of catastrophic failures.
      # Thus, it is possible that we do not have a sane result message.
      if result is not None:
        result.log_data.gs_url = gs_res.gs_url
        result.log_data.stainless_url = _stainless_logs_from_gs_path(
            gs_res.gs_url)
  return result


def _logs_gs_dir(api, gs_root):
  # Create a reasonable directory tree to avoid directories with a huge
  # number of entries.
  # - b/167219452 - Large number of entries at top-level can cause Google
  #   Storage meltdown.
  # - Being able to easily crawl the logs chronologically is very useful.
  # - Inject a random element to
  #   - keep logs across tasks on a single day separate
  #   - make it harder to hard-code paths to the target directory
  #     downstream.
  now = api.time.utcnow()
  return '%s/%s/%s' % (gs_root, now.date().isoformat(), api.uuid.random())


def _stainless_logs_from_gs_path(path):
  """Convert a GS path to a stainless logs browser URL."""
  assert path.startswith('gs://'), "{} should start with gs://".format(path)
  return 'https://stainless.corp.google.com/browse/%s' % path[len('gs://'):]


def upload_to_tko(api, config=None):
  """Upload test results to TKO via `tko/parse`.

  Args:
    * config: phosphorus.Config instance.

  Raises:
    * InfraFailure if binary call fails.
  """
  with api.step.nest('upload to TKO') as step:
    with api.context(infra_steps=True):
      api.phosphorus.upload_to_tko(
          phosphorus.upload_to_tko.UploadToTkoRequest(config=config))


def get_results(api, results_dir=""):
  """Parse test results.

  Args:
    * results_dir: Directory containing test results to be parsed.

  Returns: skylab_test_runner.Result.

  Raises:
    * InfraFailure if binary call fails.
  """
  with api.step.nest('get test results') as step:
    with api.context(infra_steps=True):
      return api.autotest_status_parser.parse(results_dir)


def summarize_results(api, prejob_response, run_test_responses, result):
  """Display test cases as recipe substeps.

  Args:
    * prejob_response: phosphorus.prejob.PrejobResponse instance.
    * run_test_responses: dictionary of phosphorus.runtest.RunTestResponse instances.
    * result: skylab_test_runner.Result instance.
  """
  with api.step.nest('test results') as step:
    if result.log_data.stainless_url:
      step.links['Autotest logs'] = result.log_data.stainless_url
    step.presentation.logs['JSON output'] = json_format.MessageToJson(result)
    for prejob in result.prejob.step:
      with api.step.nest(prejob.name) as step:
        if prejob.verdict != Result.Prejob.Step.VERDICT_PASS:
          step.presentation.status = api.step.FAILURE
        if prejob.human_readable_summary:
          step.presentation.logs['summary'] = prejob.human_readable_summary
    for test_id, ar in result.autotest_results.items():
      with api.step.nest(test_id):
        for tc in ar.test_cases:
          with api.step.nest(tc.name) as step:
            if tc.verdict != Result.Autotest.TestCase.VERDICT_PASS:
              step.presentation.status = api.step.FAILURE
            if tc.human_readable_summary:
              step.presentation.logs['summary'] = tc.human_readable_summary
      if result.autotest_result.incomplete:
        with api.step.nest("autoserv") as step:
          step.presentation.status = api.step.FAILURE
          step.presentation.logs['summary'] = (
              "autoserv crashed. The test list "
              "is likely incomplete. Consult autoserv.ERROR for more details.")
    if (_result_contains_no_failures(result) and
        _prejob_failed(prejob_response)):
      with api.step.nest('prejob execution') as step:
        step.presentation.status = api.step.FAILURE
        step.presentation.logs['summary'] = (
            "ended with unsuccessful state %s" %
            phosphorus.prejob.PrejobResponse.State.Name(prejob_response.state))
    for test_id, rtr in run_test_responses.items():
      if (_result_contains_no_failures(result) and _test_failed(rtr)):
        with api.step.nest(
            'test execution for test: {}'.format(test_id)) as step:
          step.presentation.status = api.step.FAILURE
          step.presentation.logs['summary'] = (
              "ended with unsuccessful state %s" %
              phosphorus.runtest.RunTestResponse.State.Name(rtr.state))


def _result_contains_no_failures(result):
  return not _result_contains_failures(result)

def _result_contains_failures(result):
  verdicts = [
      p.verdict != Result.Prejob.Step.VERDICT_PASS for p in result.prejob.step
  ]

  incomplete = []

  for test_result in result.autotest_results.values():
    if test_result.incomplete:
      incomplete.append(test_result)
    for t in test_result.test_cases:
      if t.verdict != Result.Autotest.TestCase.VERDICT_PASS:
        verdicts.append(t)

  return any(verdicts) or result.autotest_result.incomplete or any(incomplete)


def set_output_properties(api, result=None):
  """Set the output properties that are part of the test_runner API.

  Args:
    * result: skylab_test_runner.Result instance.
  """
  with api.context(infra_steps=True):
    with api.step.nest('set output properties') as step:
      step.properties['compressed_result'] = (
          result.SerializeToString().encode('zlib_codec').encode('base64_codec')
      )


def _get_phosphorus_config(recipe_config, load_response):
  """Construct a phosphorus.Config.

  Args:
    * recipe_config: skylab_test_runner.Config instance.
    * load_response: skylab_local_state.LoadResponse instance.

  Returns: phosphorus.Config.
  """
  subdir = os.path.join(load_response.results_dir, "autoserv_test")
  return phosphorus.common.Config(
      log_data_upload_step=recipe_config.log_data_upload_step,
      bot=phosphorus.common.BotEnvironment(
          autotest_dir=recipe_config.harness.autotest_dir,
      ),
      task=phosphorus.common.TaskEnvironment(
          results_dir=load_response.results_dir,
          ssp_base_image_name=recipe_config.harness.ssp_base_image_name,
          test_results_dir=subdir,
      ),
  )


def _upload_to_tko_config(api, phosphorus_config, run_test_response):
  """Construct a phosphorus.Config specific to upload_to_tko step.

  Unlike other steps, upload_to_tko needs to be pointed to the test-specific
  subdirectory of the overall results directory.

  Args:
  * phosphorus_config: phosphorus.Config instance.
  * run_test_response: phosphorus.RunTestResponse instance.

  Returns: phosphorus.Config.

  Raises:
  * InfraFailure.
  """
  task_results_dir = phosphorus_config.task.results_dir
  test_results_dir = run_test_response.results_dir
  if not test_results_dir.startswith(task_results_dir):
    raise api.step.InfraFailure(
        'test results dir %s is not a subdirectory of task results dir %s' %
        (test_results_dir, task_results_dir))

  ret = phosphorus.common.Config()
  ret.CopyFrom(phosphorus_config)
  ret.task.results_dir = test_results_dir
  return ret


def _collect_tests(request):
  """Collects tests from Request into one dictionary

  Args:
  * request: skylab_test_runner.Request instance

  Returns: dictionary of skylab_test_runner.Request.Test instances
  """
  tests = {i: t for (i, t) in request.tests.items()}
  if request.HasField('test'):
    tests['original_test'] = request.test
  return tests


def publish_to_result_flow(api, config, request,
                           should_poll_for_completion=False):
  """Publish build info to result_flow PubSub

  Args:
  * config: test_runner.Config instance.
  * request: test_runner.Request instance.
  * should_poll_for_completion (bool): If true, the consumers should not ACK
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


_DUT_STATE_NEEDS_REPAIR = "needs_repair"


def execution_steps(api, properties):
  """Runs all the non-UI-related steps.

  Args:
  * properties: TestRunnerProperties instance.

  Returns:
    A tuple of three responses generated by the steps:
    * phosphorus.PrejobResponse,
    * dictionary of phosphorus.RunTestResponses,
    * test_runner.Result.

  Raises:
  * InfraFailure.
  """
  tests = _collect_tests(properties.request)
  autotest_results = {}
  prejob_response = None
  run_test_responses = {}

  with api.step.nest('execution steps') as step:
    build = api.buildbucket.build
    # Providing link to parent if parent tag exists.
    parent = [x.value for x in build.tags if x.key == 'parent_buildbucket_id']
    if parent:
      step.links['parent link'] = (
          api.buildbucket.build_url(build_id=parent[0]))
    publish_to_result_flow(api, properties.config, properties.request)
    dut_hostname = api.phosphorus.read_dut_hostname()

    for test_id, test in tests.items():
      with api.step.nest(test_id):
        validate_request(api, test)
        # Needs to be distinct per test as logs are uploaded for each test separately.
        logs_gs_dir = _logs_gs_dir(api,
                                   properties.config.output.log_data_gs_root)

        with api.step.nest('load local DUT state'):
          load_response = api.phosphorus.load_skylab_local_state(
              test_id=test_id)
        with api.step.nest('mark local DUT state dirty'):
          api.phosphorus.save_skylab_local_state(_DUT_STATE_NEEDS_REPAIR)

        phosphorus_config = _get_phosphorus_config(
            properties.config,
            load_response,
        )

        dut_state = _DUT_STATE_NEEDS_REPAIR
        run_test_response = None
        max_duration_sec = (
            properties.config.harness.prejob_deadline_seconds or 24 * 60 * 60)
        result = None

        try:
          # prejob and test failures are detected when parsing results.
          # An exception from the steps here indicates an infrastructure
          # failure that should be bubbled up immediately.
          prejob_response = prejob(api, config=phosphorus_config,
                                   request=properties.request,
                                   dut_hostname=dut_hostname,
                                   load_response=load_response,
                                   max_duration_seconds=max_duration_sec)

          if not _prejob_failed(prejob_response):
            run_test_response = run_test(
                api,
                config=phosphorus_config,
                request=properties.request,
                output_config=properties.config.output,
                dut_hostname=dut_hostname,
                test=test,
                logs_gs_dir=logs_gs_dir,
            )
            upload_to_tko(
                api,
                config=_upload_to_tko_config(
                    api,
                    phosphorus_config,
                    run_test_response,
                ),
            )

            run_test_responses[test_id] = run_test_response
            result = get_results(api, load_response.results_dir)
            if result.HasField('autotest_result'):
              autotest_results[test_id] = result.autotest_result
            dut_state = result.state_update.dut_state
          else:
            result = get_results(api, load_response.results_dir)
        finally:
          # Must complete synchronous logs upload before sealing the results
          # directory. Once the results directory is sealed, gs_offloader may delete
          # the result files.
          result = archive_all_logs(
              api,
              phosphorus_config=phosphorus_config,
              gs_dir=logs_gs_dir,
              result=result,
          )

          with api.step.nest('save local DUT state'):
            api.phosphorus.save_and_seal_skylab_local_state(dut_state)
          publish_to_result_flow(api, properties.config, properties.request,
                                 should_poll_for_completion=True)
        set_output_properties(api, result=result)

  for test_id, test_result in autotest_results.items():
    result.autotest_results[test_id].CopyFrom(test_result)

  return prejob_response, run_test_responses, result


def RunSteps(api, properties):
  prejob_response, run_test_responses, result = execution_steps(api, properties)

  summarize_results(api, prejob_response, run_test_responses, result)

  if _is_failure(prejob_response, run_test_responses, result):
    with api.step.nest('build status'):
      raise api.step.StepFailure('prejob or test failed')


def _is_failure(prejob_response, run_test_responses, result):
  return (_result_contains_failures(result) or
          _prejob_failed(prejob_response) or _tests_failed(run_test_responses))


def _prejob_failed(prejob_response):
  return (prejob_response and
          prejob_response.state != phosphorus.prejob.PrejobResponse.SUCCEEDED)


def _tests_failed(run_test_responses):
  for rtr in run_test_responses.values():
    if rtr.state != phosphorus.runtest.RunTestResponse.SUCCEEDED:
      return True
  return False


def _test_failed(run_test_response):
  return (
      run_test_response and
      run_test_response.state != phosphorus.runtest.RunTestResponse.SUCCEEDED)


def GenTests(api):
  _gs_root = "gs://bucket/foo/bar"
  _sync_subdir = "synchronous_subdir"

  def _set_build_id(id, tags=None):
    # tags is a dict, convert that into [StringPair].
    bb_tags = api.cros_tags.tags(**tags) if tags else []
    return api.buildbucket.build(build_pb2.Build(id=id, tags=bb_tags))

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
                    'synch_offload_subdir': _sync_subdir,
                    'prejob_deadline_seconds': 60 * 60,
                },
                'output': {
                    'gs_root_dir': _gs_root,
                    'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
                },
                'result_flow_pubsub': {
                    'project': 'foo-proj',
                    'topic': 'foo-topic',
                },
            }), **{
                '$chromeos/autotest_status_parser':
                    AutotestStatusParserProperties(
                        version=AutotestStatusParserProperties.Version(
                            cipd_label='asp_prod')),
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

  def _canned_test_runner_request():
    return {
        'prejob': {
            'provisionable_labels': {
                'label1': 'value1'
            }
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
        }
    }

  def _canned_request_missing_name():
    return {'test': {'autotest': {'display_name': 'name'}}}

  def _canned_multitest_request():
    return {
        'prejob': {
            'provisionable_labels': {
                'label1': 'value1',
                'label2': 'value2',
            }
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

  # Required for steps following `skylab_local_state load`.
  def _mock_load_step(test_id='original_test'):
    return (api.step_data(
        'execution steps.%s.load local DUT state.call `phosphorus`.load' %
        test_id, stdout=api.raw_io.output(
            json_format.MessageToJson(
                skylab_local_state.load.LoadResponse(
                    results_dir='dummy-results-dir')))))

  def _successful_prejob_step(test_id='original_test'):
    return _prejob_step_with_state(phosphorus.prejob.PrejobResponse.SUCCEEDED,
                                   test_id)

  def _prejob_step_with_state(state, test_id='original_test'):
    return (api.step_data(
        'execution steps.%s.run prejob.call `phosphorus`.prejob' % test_id,
        stdout=api.raw_io.output(
            json_format.MessageToJson(
                phosphorus.prejob.PrejobResponse(state=state)))))

  def _successful_run_test_step():
    return _run_test_step_with_state(
        phosphorus.runtest.RunTestResponse.SUCCEEDED)

  def _run_test_step_with_state(state, test_id='original_test'):
    return (api.step_data(
        'execution steps.%s.run test.call `phosphorus`.run-test' % test_id,
        stdout=api.raw_io.output(
            json_format.MessageToJson(
                phosphorus.runtest.RunTestResponse(
                    results_dir='dummy-results-dir/subdir', state=state)))))

  def _successful_logs_archive_step(test_id='original_test'):
    return api.step_data(
        'execution steps.%s.archive all test logs to Google Storage.'
        'call `phosphorus`.upload-to-gs' % test_id, stdout=api.raw_io.output(
            json_format.MessageToJson(
                phosphorus.upload_to_gs.UploadToGSResponse(
                    gs_url='gs://chromeos-test-logs/common-env/UUID/logs'))))

  yield api.test(
      'test_name_missing',
      _misc_properties(),
      _request_properties_no_name(),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'success',
      _set_build_id(id=42, tags={'parent_buildbucket_id': '1234'}),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_logs_archive_step(),
  )

  r_with_deadline = _canned_test_runner_request()
  current_time_sec = 2369692800
  r_with_deadline['deadline'] = timestamp_pb2.Timestamp(
      seconds=current_time_sec + 55)

  yield api.test(
      'success_with_build_deadline',
      api.buildbucket.build(_build_with_execution_timeout(30)),
      _misc_properties(),
      api.properties(TestRunnerProperties(request=r_with_deadline)),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_logs_archive_step(),
  ) + api.time.seed(current_time_sec)

  yield api.test(
      'success_with_request_deadline',
      api.buildbucket.build(_build_with_execution_timeout(66)),
      _misc_properties(),
      api.properties(TestRunnerProperties(request=r_with_deadline)),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_logs_archive_step(),
  ) + api.time.seed(current_time_sec)

  yield api.test(
      'prejob_crash',
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      api.step_data(
          'execution steps.original_test.run prejob.call `phosphorus`.prejob',
          retcode=1),
  )

  yield api.test(
      'run_test_crash',
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      api.step_data(
          'execution steps.original_test.run test.call `phosphorus`.run-test',
          retcode=1),
  )

  yield api.test(
      'upload_to_tko_crash',
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      api.step_data(
          'execution steps.original_test.upload to TKO.call `phosphorus`.upload-to-tko',
          retcode=1),
  )

  yield api.test(
      'mismatched_test_result_directory',
      _misc_properties(),
      _request_properties(),
      api.step_data(
          'execution steps.original_test.load local DUT state.call `phosphorus`.load',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  skylab_local_state.load.LoadResponse(
                      results_dir='dummy-results-dir')))),
      _successful_prejob_step(),
      api.step_data(
          'execution steps.original_test.run test.call `phosphorus`.run-test',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  phosphorus.runtest.RunTestResponse(
                      results_dir='not-a-subdir-of-dummy-results-dir',
                      state=phosphorus.runtest.RunTestResponse.SUCCEEDED)))),
  )

  yield api.test(
      'link_to_all_archived_logs',
      _set_build_id(id=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      api.step_data(
          'execution steps.original_test.get test results.'
          'call `autotest_status_parser`.parse', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  Result(
                      autotest_result=Result.Autotest(test_cases=[]),
                  )))),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'get_results_crash',
      _set_build_id(id=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      api.step_data(
          'execution steps.original_test.get test results.'
          'call `autotest_status_parser`.parse', retcode=1),
  )

  yield api.test(
      'results_summary',
      _set_build_id(id=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_logs_archive_step(),
      api.step_data(
          'execution steps.original_test.get test results.call `autotest_status_parser`.'
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
      _set_build_id(id=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _prejob_step_with_state(phosphorus.prejob.PrejobResponse.FAILED),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'failed_run-test_with_missing_failures_in_result',
      _set_build_id(id=42),
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _run_test_step_with_state(phosphorus.runtest.RunTestResponse.FAILED),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'successful_run-test_with_multiple_tests',
      _set_build_id(id=42),
      _misc_properties(),
      _request_properties_multitest(),
      _mock_load_step(test_id='multi_test_2'),
      _successful_prejob_step(test_id='multi_test_2'),
      _run_test_step_with_state(phosphorus.runtest.RunTestResponse.SUCCEEDED,
                                test_id='multi_test_2'),
      _successful_logs_archive_step(test_id='multi_test_2'),
  )

  yield api.test(
      'skip_result_flow_pubsub_due_to_missing_build_ID',
      _misc_properties(),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'skip_result_flow_pubsub_due_to_missing_topic',
      _set_build_id(id=42),
      _misc_properties(),
      api.properties(
          TestRunnerProperties(
              config={
                  'result_flow_pubsub': {
                      'topic': '',
                      'project': 'foo-proj',
                  },
                  'output': {
                      'gs_root_dir': _gs_root,
                      'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
                  },
              })),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_logs_archive_step(),
  )

  yield api.test(
      'skip_result_flow_pubsub_due_to_missing_project',
      _set_build_id(id=42),
      _misc_properties(),
      api.properties(
          TestRunnerProperties(
              config={
                  'result_flow_pubsub': {
                      'topic': 'foo-topic',
                      'project': '',
                  },
                  'output': {
                      'gs_root_dir': _gs_root,
                      'log_data_gs_root': 'gs://chromeos-test-logs/common-env',
                  },
              })),
      _request_properties(),
      _mock_load_step(),
      _successful_prejob_step(),
      _successful_run_test_step(),
      _successful_logs_archive_step(),
  )
