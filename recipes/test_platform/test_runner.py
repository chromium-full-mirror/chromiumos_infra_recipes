# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Skylab Test Runner."""

import os

from PB.recipe_modules.chromeos.phosphorus.phosphorus \
  import PhosphorusProperties
from PB.recipe_modules.chromeos.autotest_status_parser.autotest_status_parser \
  import AutotestStatusParserProperties
from PB.recipe_modules.chromeos.skylab_local_state.skylab_local_state import \
  SkylabLocalStateProperties
from PB.recipes.chromeos.test_platform.test_runner import \
  TestRunnerProperties, TestRunnerEnvProperties
from PB.test_platform import phosphorus
from PB.test_platform import skylab_local_state
from PB.test_platform.skylab_test_runner.result import Result
from PB.test_platform.skylab_test_runner.config import Config

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

DEPS = [
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'autotest_status_parser',
    'phosphorus',
    'skylab_local_state'
]

PROPERTIES = TestRunnerProperties
ENV_PROPERTIES = TestRunnerEnvProperties

def validate_request(api, properties):
  """Validate the TestRunnerProperties.

  Args:
    * properties: TestRunnerProperties instance.

  Raises:
    * ValueError if there are invalid properties.
  """
  with api.step.nest('validate request'):
    if not properties.request.test.autotest.name:
      raise ValueError("Test name must be specified")


def prejob(api, config=None, request=None, dut_hostname='',
           load_response=None):
  """Run a prejob (e.g. provision) against the DUT via `autoserv`.

  Args:
    * config: phosphorus.Config instance.
    * request: skylab_test_runner.Request instance.
    * dut_hostname: DUT hostname string.
    * load_response: LoadStateResponse instance.

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
      )
      if request.HasField('deadline'):
        # Must explicitly check for existence of deadline.
        # Reading the deadline from a request where the field is unset returns
        # the zero value. The zero value google.protobuf.Timestamp translates to
        # a non-zero time.Time in Go.
        prejob_request.deadline.MergeFrom(request.deadline)
      return api.phosphorus.prejob(prejob_request)


def run_test(api,
             config=None, request=None, output_config=None, dut_hostname=''):
  """Run a test against the DUT via `autoserv`.

  Args:
    * config: phosphorus.Config instance.
    * request: skylab_test_runner.Request instance.
    * output_config: skylab_test_runner.Config.Output instance.
    * dut_hostname: DUT hostname string.

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
            name=request.test.autotest.name,
            test_args=request.test.autotest.test_args,
            display_name=request.test.autotest.display_name,
            keyvals=request.test.autotest.keyvals,
            is_client_test=request.test.autotest.is_client_test,
        ),
        environment=phosphorus.runtest.RunTestRequest.Environment(
            gs_root_dir=output_config.gs_root_dir
        ),
    )
    if request.HasField('deadline'):
      # Must explicitly check for existence of deadline.
      # Reading the deadline from a request where the field is unset returns
      # the zero value. The zero value google.protobuf.Timestamp translates to
      # a non-zero time.Time in Go.
      run_test_request.deadline.MergeFrom(request.deadline)
    return api.phosphorus.run_test(run_test_request)


def upload_sync_results(api, config=None, output_config=None):
  """Upload synchronously-needed test results to Google Storage.

  Args:
    * config: phosphorus.Config instance
    * output_config: skylab_test_runner.Config.Output instance.
  Returns:
    UploadToGSResponse proto
  Raises:
    * InfraFailure if binary call fails.
  """
  with api.context(infra_steps=True):
    with api.step.nest('upload results to GS') as step:
      req = phosphorus.upload_to_gs.UploadToGSRequest(
          config=config,
          gs_directory=output_config.gs_root_dir)
      return api.phosphorus.upload_to_gs(req)


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


def summarize_results(api, prejob_response, run_test_response, result):
  """Display test cases as recipe substeps.

  Args:
    * prejob_response: phosphorus.prejob.PrejobResponse instance.
    * run_test_response: phosphorus.runtest.RunTestResponse instance.
    * result: skylab_test_runner.Result instance.
  """
  with api.step.nest('test results'):
    for prejob in result.prejob.step:
      with api.step.nest(prejob.name) as step:
        if prejob.verdict != Result.Prejob.Step.VERDICT_PASS:
          step.presentation.status = api.step.FAILURE
        if prejob.human_readable_summary:
          step.presentation.logs['summary'] = prejob.human_readable_summary
    for tc in result.autotest_result.test_cases:
      with api.step.nest(tc.name) as step:
        if tc.verdict != Result.Autotest.TestCase.VERDICT_PASS:
          step.presentation.status = api.step.FAILURE
        if tc.human_readable_summary:
          step.presentation.logs['summary'] = tc.human_readable_summary
    if result.autotest_result.incomplete:
      with api.step.nest("autoserv") as step:
        step.presentation.status = api.step.FAILURE
        step.presentation.logs['summary'] = ("autoserv crashed. The test list "
            "is likely incomplete. Consult autoserv.ERROR for more details.")
    if (_result_contains_no_failures(result) and
        prejob_response.state != phosphorus.prejob.PrejobResponse.SUCCEEDED):
      with api.step.nest('prejob execution') as step:
        step.presentation.status = api.step.FAILURE
        step.presentation.logs['summary'] = (
            "ended with unsuccessful state %s" %
            phosphorus.prejob.PrejobResponse.State.Name(prejob_response.state))
    if (_result_contains_no_failures(result) and run_test_response.state !=
        phosphorus.runtest.RunTestResponse.SUCCEEDED):
      with api.step.nest('test execution') as step:
        step.presentation.status = api.step.FAILURE
        step.presentation.logs['summary'] = (
            "ended with unsuccessful state %s" %
            phosphorus.runtest.RunTestResponse.State.Name(
                run_test_response.state))


def _result_contains_no_failures(result):
  return not _result_contains_failures(result)


def _result_contains_failures(result):
  verdicts = [
      p.verdict != Result.Prejob.Step.VERDICT_PASS for p in result.prejob.step
  ]
  verdicts += [
      t.verdict != Result.Autotest.TestCase.VERDICT_PASS
      for t in result.autotest_result.test_cases
  ]
  return any(verdicts) or result.autotest_result.incomplete


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


def _get_dut_hostname(api, env):
  """Extract the DUT hostname from the env vars.

  Args:
    * env: TestRunnerEnvProperties instance.

  Raises:
    * AssertionError if the Swarming bot ID env var is missing or invalid.
  """
  with api.context(infra_steps=True):
    with api.step.nest('determine target DUT') as step:
      # TODO(zamorzaev): this is brittle, propagate the DUT hostname directly
      # instead.
      assert env.SWARMING_BOT_ID[:7] == 'crossk-'
      return env.SWARMING_BOT_ID[7:]


def _get_phosphorus_config(recipe_config, load_response, set_offload_dir):
  """Construct a phosphorus.Config.

  Args:
    * recipe_config: skylab_test_runner.Config instance.
    * load_response: skylab_local_state.LoadResponse instance.
    * set_offload_dir: whether to embed the GS offload dir into the config.
        This will be used if set, so setting it where it is inapplicable (such
        as for a non-test task) will result in a downstream error.

  Returns: phosphorus.Config.
  """
  if set_offload_dir:
    off_dir = recipe_config.harness.synch_offload_subdir
  else:
    off_dir = ""
  subdir = os.path.join(load_response.results_dir, "autoserv_test")
  return phosphorus.common.Config(
      bot=phosphorus.common.BotEnvironment(
          autotest_dir=recipe_config.harness.autotest_dir,
      ),
      task=phosphorus.common.TaskEnvironment(
          synchronous_offload_dir=off_dir,
          results_dir=load_response.results_dir,
          test_results_dir=subdir,
      )
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



_DUT_STATE_NEEDS_REPAIR = "needs_repair"


def execution_steps(api, properties, envvars):
  """Runs all the non-UI-related steps.

  Args:
  * phosphorus_config: phosphorus.Config instance.
  * run_test_response: phosphorus.RunTestResponse instance.

  Returns:
    A tuple of three responses generated by the steps:
    * phosphorus.PrejobResponse,
    * phosphorus.RunTestResponse,
    * test_runner.Result.

  Raises:
  * InfraFailure.
  """
  with api.step.nest('execution steps'):
    upload_response = None
    validate_request(api, properties)
    dut_hostname = _get_dut_hostname(api, envvars)

    state_store = SkylabStateStore(
        config=properties.config,
        dut_hostname=dut_hostname,
        dut_id=envvars.SKYLAB_DUT_ID,
        run_id=envvars.SWARMING_TASK_ID,
    )
    with api.step.nest('load local DUT state'):
      load_response = state_store.load(api)
    with api.step.nest('mark local DUT state dirty'):
      state_store.save(api, _DUT_STATE_NEEDS_REPAIR)


    phosphorus_config = _get_phosphorus_config(
        properties.config, load_response,
        properties.request.test.offload.synchronous_gs_enable,
    )

    dut_state = _DUT_STATE_NEEDS_REPAIR
    prejob_response = None
    run_test_response = None
    try:
      # prejob and test failures are detected when parsing results.
      # An exception from the steps here indicates an infrastructure
      # failure that should be bubbled up immediately.
      prejob_response = prejob(
          api, config=phosphorus_config, request=properties.request,
          dut_hostname=dut_hostname, load_response=load_response)
      run_test_response = run_test(api,
                                  config=phosphorus_config,
                                  request=properties.request,
                                  output_config=properties.config.output,
                                  dut_hostname=dut_hostname)

      # In case autoserv fails early, upload_to_tko()reruns tko/parse to extract
      # status.log from the logs. Thus, upload_to_tko() must be run before
      # get_results().
      upload_to_tko(api, config=_upload_to_tko_config(api,
                                                      phosphorus_config,
                                                      run_test_response))
      result = get_results(api, load_response.results_dir)
      dut_state = result.state_update.dut_state

      if properties.request.test.offload.synchronous_gs_enable:
        upload_response = upload_sync_results(
            api, config=phosphorus_config,
            output_config=properties.config.output)
        result.autotest_result.synchronous_log_data_url = upload_response.gs_url
    finally:
      with api.step.nest('save local DUT state'):
        state_store.save_and_seal(api, dut_state)
    set_output_properties(api, result=result)
    return prejob_response, run_test_response, result


def RunSteps(api, properties, envvars):
  prejob_response, run_test_response, result = execution_steps(
      api, properties, envvars)

  summarize_results(api, prejob_response, run_test_response, result)

  if _is_failure(prejob_response, run_test_response, result):
    with api.step.nest('build status'):
      raise api.step.StepFailure('prejob or test failed')


def _is_failure(prejob_response, run_test_response, result):
  return (
      _result_contains_failures(result) or
      prejob_response.state != phosphorus.prejob.PrejobResponse.SUCCEEDED or
      run_test_response.state != phosphorus.runtest.RunTestResponse.SUCCEEDED)


class SkylabStateStore(object):
  """Wrapper for skylab_local_state interaction."""

  def __init__(self, config, dut_hostname, dut_id, run_id):
    """Initialize us.

    Args:
      * config: skylab_test_runner.Config instance.
      * results_dir: The root directory of test results.
      * dut_hostname: DUT hostname string (e.g. 'chromeos8-row8-rack8-host8').
      * dut_id: DUT ID string (e.g. 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee').
      * run_id: Swarming task run ID string.
    """
    self._config = config
    self._dut_hostname = dut_hostname
    self._dut_id = dut_id
    self._run_id = run_id
    self._results_dir = ''

  def load(self, api):
    """Create a host info file.

    Returns: LoadResponse.

    Raises:
      * InfraFailure
    """
    with api.context(infra_steps=True):
      load_request = skylab_local_state.load.LoadRequest(
          config=skylab_local_state.common.Config(
              admin_service=self._config.lab.admin_service,
              autotest_dir=self._config.harness.autotest_dir,
          ), dut_name=self._dut_hostname, run_id=self._run_id)
      r = api.skylab_local_state.load(load_request)
      self._results_dir = r.results_dir
      return r

  def save(self, api, dut_state):
    """Update the local DUT state file.

    Args:
      * dut_state: DUT state string (e.g. 'ready').

    Raises:
      * InfraFailure
    """
    return self._save(api, dut_state, False)

  def save_and_seal(self, api, dut_state):
    """Update the local DUT state file and seal the results directory.

    Args:
      * dut_state: DUT state string (e.g. 'ready').

    Raises:
      * InfraFailure
    """
    return self._save(api, dut_state, True)

  def _save(self, api, dut_state, seal_results_dir):
    with api.context(infra_steps=True):
      assert self._results_dir, (
          'Results directory not set. Did you call load() first?')

      save_request = skylab_local_state.save.SaveRequest(
          config=skylab_local_state.common.Config(
              admin_service=self._config.lab.admin_service,
              autotest_dir=self._config.harness.autotest_dir,
          ), results_dir=self._results_dir, dut_name=self._dut_hostname,
          dut_id=self._dut_id, dut_state=dut_state,
          seal_results_dir=seal_results_dir)
      api.skylab_local_state.save(save_request)


def GenTests(api):
  _gs_root = "gs://bucket/foo/bar"
  _sync_subdir = "synchronous_subdir"
  # Required for initial module set up.
  def _misc_properties():
    return (
        api.properties(
            TestRunnerProperties(
                config={
                    'lab': {
                        'admin_service': 'foo-service'
                    },
                    'harness': {
                        'autotest_dir': '/path/to/autotest',
                        'synch_offload_subdir': _sync_subdir
                    },
                    'output': {
                        'gs_root_dir': _gs_root
                    }}),
            **{
                '$chromeos/autotest_status_parser':
                    AutotestStatusParserProperties(
                        version=AutotestStatusParserProperties.Version(
                            cipd_label='asp_prod')),
                '$chromeos/skylab_local_state':
                    SkylabLocalStateProperties(
                        version=SkylabLocalStateProperties.Version(
                            cipd_label='sls_prod')),
                '$chromeos/phosphorus':
                    PhosphorusProperties(
                        version=PhosphorusProperties.Version(
                            cipd_label='phosphorus_prod'))}) + #
        api.properties.environ(TestRunnerEnvProperties(
            SWARMING_BOT_ID='crossk-dummy',
            SWARMING_TASK_ID='dummy-task-id',
            SKYLAB_DUT_ID='dummy-dut-id')))

  # An example request.
  def _request_properties():
    return (api.properties(
        TestRunnerProperties(request=_canned_test_runner_request())))

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

  # Required for steps following `skylab_local_state load`.
  def _mock_load_step():
    return (
      api.step_data(
      'execution steps.load local DUT state.call `skylab_local_state`.load',
      stdout=api.raw_io.output(
          json_format.MessageToJson(
              skylab_local_state.load.LoadResponse(
              results_dir='dummy-results-dir')))))


  def _successful_prejob_step():
    return _prejob_step_with_state(phosphorus.prejob.PrejobResponse.SUCCEEDED)

  def _prejob_step_with_state(state):
    return (api.step_data(
        'execution steps.run prejob.call `phosphorus`.prejob',
        stdout=api.raw_io.output(
            json_format.MessageToJson(
                phosphorus.prejob.PrejobResponse(state=state)))))

  def _successful_run_test_step():
    return _run_test_step_with_state(
        phosphorus.runtest.RunTestResponse.SUCCEEDED)

  def _run_test_step_with_state(state):
    return (api.step_data(
        'execution steps.run test.call `phosphorus`.run-test',
        stdout=api.raw_io.output(
            json_format.MessageToJson(
                phosphorus.runtest.RunTestResponse(
                  results_dir='dummy-results-dir/subdir',
                  state=state)))))


  yield (api.test('test_name_missing') + #
         _misc_properties() + #
         api.expect_exception('ValueError'))

  yield (api.test('success') +  #
         _misc_properties() +  #
         _request_properties() +  #
         _mock_load_step() +  #
         _successful_prejob_step() +  #
         _successful_run_test_step())

  r = _canned_test_runner_request()
  r['deadline'] = timestamp_pb2.Timestamp(seconds=55)
  yield (api.test('success with deadline') +  #
         _misc_properties() +  #
         api.properties(TestRunnerProperties(request=r)) +  #
         _mock_load_step() +  #
         _successful_prejob_step() +  #
         _successful_run_test_step())

  yield (api.test('prejob_crash') + #
         _misc_properties() + #
         _request_properties() + #
         _mock_load_step() + #
         api.step_data(
             'execution steps.run prejob.call `phosphorus`.prejob',
             retcode=1))

  yield (api.test('run_test_crash') + #
         _misc_properties() + #
         _request_properties() + #
         _mock_load_step() + #
         api.step_data(
             'execution steps.run test.call `phosphorus`.run-test',
             retcode=1))

  yield (
      api.test('upload_to_tko_crash') +  #
      _misc_properties() +  #
      _request_properties() +  #
      _mock_load_step() +  #
      _successful_prejob_step() +  #
      _successful_run_test_step() +  #
      api.step_data(
          'execution steps.upload to TKO.call `phosphorus`.upload-to-tko',
          retcode=1))

  yield (
      api.test('mismatched test result directory') +  #
      _misc_properties() +  #
      _request_properties() +  #
      api.step_data(
          'execution steps.load local DUT state.call `skylab_local_state`.load',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  skylab_local_state.load.LoadResponse(
                  results_dir='dummy-results-dir')))) + #
      _successful_prejob_step() +  #
      api.step_data(
          'execution steps.run test.call `phosphorus`.run-test',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  phosphorus.runtest.RunTestResponse(
                    results_dir='not-a-subdir-of-dummy-results-dir',
                    state=phosphorus.runtest.RunTestResponse.SUCCEEDED)))))

  yield (api.test('upload_to_gs') +  #
         _misc_properties() +  #
         _mock_load_step() +  #
         _successful_prejob_step() +  #
         _successful_run_test_step() +  #
         api.properties(
             TestRunnerProperties(
                 request={
                     'test': {
                         'autotest': {
                             'name': 'dummy_name'
                         },
                         'offload': {
                             'synchronous_gs_enable': True
                         }
                     }
                 })) +  #
         api.step_data(
             'execution steps.get test results.'
             'call `autotest_status_parser`.parse',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     Result(
                         autotest_result=Result.Autotest(test_cases=[]),
                     )))) +  #
         api.step_data(
             'execution steps.upload results to GS.'
             'call `phosphorus`.upload-to-gs',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     phosphorus.upload_to_gs.UploadToGSResponse(
                         gs_url=os.path.join(_gs_root,
                                             "UUID",
                                             _sync_subdir))))))
  yield (api.test('get_results_crash') +  #
         _misc_properties() +  #
         _request_properties() +  #
         _mock_load_step() +  #
         _successful_prejob_step() +  #
         _successful_run_test_step() +  #
         api.step_data('execution steps.get test results.'
                       'call `autotest_status_parser`.parse',
                       retcode=1))

  yield (
      api.test('results_summary') +  #
      _misc_properties() +  #
      _request_properties() +  #
      _mock_load_step() +  #
      _successful_prejob_step() +  #
      _successful_run_test_step() +  #
      api.step_data(
          'execution steps.get test results.call `autotest_status_parser`.'
          'parse',
          stdout=api.raw_io.output(
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
                          ], incomplete=True))))))

  yield (api.test('failed prejob with missing failures in result') +  #
         _misc_properties() +  #
         _request_properties() +  #
         _mock_load_step() +  #
         _prejob_step_with_state(phosphorus.prejob.PrejobResponse.FAILED) +  #
         _successful_run_test_step())

  yield (api.test('failed run-test with missing failures in result') +  #
         _misc_properties() +  #
         _request_properties() +  #
         _mock_load_step() +  #
         _successful_prejob_step() +  #
         _run_test_step_with_state(phosphorus.runtest.RunTestResponse.FAILED))
