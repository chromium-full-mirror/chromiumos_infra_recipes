# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Skylab Test Runner."""

import os

from PB.recipes.chromeos.test_platform.test_runner import \
  TestRunnerProperties, TestRunnerEnvProperties
from PB.test_platform import phosphorus
from PB.test_platform import skylab_local_state
from PB.test_platform.skylab_test_runner.result import Result
from PB.test_platform.skylab_test_runner.config import Config

from google.protobuf import json_format

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


def load_state(api, config=None, dut_hostname="", run_id=""):
  """Create a host info file.

  Args:
    * config: skylab_test_runner.Config instance.
    * dut_hostname: DUT hostname string (e.g. 'chromeos8-row8-rack8-host8').
    * run_id: Swarming task run ID string.

  Returns: LoadStateResponse.

  Raises:
    * InfraFailure if binary call fails.
  """
  with api.step.nest('load local DUT state') as step:
    with api.context(infra_steps=True):
      load_request = skylab_local_state.load.LoadRequest(
          config=skylab_local_state.common.Config(
              admin_service=config.lab.admin_service,
              autotest_dir=config.harness.autotest_dir,
          ),
          dut_name=dut_hostname,
          run_id=run_id
      )
      return api.skylab_local_state.load(load_request)


def prejob(api, config=None, request=None, dut_hostname='',
           load_response=None):
  """Run a prejob (e.g. provision) against the DUT via `autoserv`.

  Args:
    * config: phosphorus.Config instance.
    * request: skylab_test_runner.Request instance.
    * dut_hostname: DUT hostname string.
    * load_response: LoadStateResponse instance.

  Raises:
    * InfraFailure if prejob fails.
  """
  with api.step.nest('run prejob') as step:
    with api.context(infra_steps=True):
      prejob_request = phosphorus.prejob.PrejobRequest(
          config=config,
          dut_hostname=dut_hostname,
          desired_provisionable_labels=request.prejob.provisionable_labels,
          existing_provisionable_labels=load_response.provisionable_labels
      )
      api.phosphorus.prejob(prejob_request)


def run_test(api, config=None, request=None, dut_hostname=''):
  """Run a test against the DUT via `autoserv`.

  Args:
    * config: phosphorus.Config instance.
    * request: skylab_test_runner.Request instance.
    * dut_hostname: DUT hostname string.

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
            is_client_test=request.test.autotest.is_client_test
        )
    )
    api.phosphorus.run_test(run_test_request)


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


def display_results_summary(api, result):
  """Display test cases as recipe substeps.

  Args:
    * result: skylab_test_runner.Result instance.
  """
  with api.step.nest('summarize test results'):
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


def save_state(api, config=None, results_dir='', dut_hostname='', dut_id='',
               dut_state=''):
  """Update the local DUT state file.

  Args:
    * config: skylab_test_runner.Config instance.
    * results_dir: The root directory of test results.
    * dut_hostname: DUT hostname string (e.g. 'chromeos8-row8-rack8-host8').
    * dut_id: DUT ID string (e.g. 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee').
    * dut_state: DUT state string (e.g. 'ready').

  Raises:
    * InfraFailure if binary call fails.
  """
  with api.step.nest('save local DUT state') as step:
    with api.context(infra_steps=True):
      save_request = skylab_local_state.save.SaveRequest(
          config=skylab_local_state.common.Config(
            admin_service=config.lab.admin_service,
            autotest_dir=config.harness.autotest_dir,
          ),
          results_dir=results_dir,
          dut_name=dut_hostname,
          dut_id=dut_id,
          dut_state=dut_state,
          seal_results_dir=True
      )
      api.skylab_local_state.save(save_request)


def set_output_properties(api, result=None):
  """Set the output properties that are part of the test_runner API.

  Args:
    * result: skylab_test_runner.Result instance.
  """
  with api.step.nest('set output properties') as step:
    with api.context(infra_steps=True):
      step.properties['result'] = json_format.MessageToDict(result)


def _get_dut_hostname(api, env):
  """Extract the DUT hostname from the env vars.

  Args:
    * env: TestRunnerEnvProperties instance.

  Raises:
    * AssertionError if the Swarming bot ID env var is missing or invalid.
  """
  # TODO(zamorzaev): this is brittle, propagate the DUT hostname directly
  # instead.
  assert env.SWARMING_BOT_ID[:7] == 'crossk-'
  return env.SWARMING_BOT_ID[7:]


def _get_phosphorus_config(recipe_config, load_response):
  """Construct a phosphorus.Config.

  Args:
    * recipe_config: skylab_test_runner.Config instance.
    * load_response: skylab_local_state.Response instance.

  Returns: phosphorus.Config.
  """
  return phosphorus.common.Config(
      bot=phosphorus.common.BotEnvironment(
          autotest_dir=recipe_config.harness.autotest_dir,
      ),
      task=phosphorus.common.TaskEnvironment(
          results_dir=load_response.results_dir,
      )
  )


def _default_failed_result():
  """Construct a result for an unkown failure.

  Returns:
    * skylab_test_runner.Result.
  """
  return Result(
      autotest_result=Result.Autotest(
        incomplete=True
      )
  )


def RunSteps(api, properties, envvars):
  validate_request(api, properties)
  dut_hostname = _get_dut_hostname(api, envvars)
  load_response = load_state(api, config=properties.config,
                              dut_hostname=dut_hostname,
                              run_id=envvars.SWARMING_TASK_ID)
  phosphorus_config = _get_phosphorus_config(properties.config,
                                             load_response)

  # Run the post-process steps if prejob or run_test fails, but don't run_test
  # if prejob fails.
  try:
    prejob(api, config=phosphorus_config, request=properties.request,
           dut_hostname=dut_hostname, load_response=load_response)

    run_test(api, config=phosphorus_config, request=properties.request,
             dut_hostname=dut_hostname)
  except (api.step.StepFailure, api.step.InfraFailure):
    pass

  try:
    upload_to_tko(api, config=phosphorus_config)
  except api.step.InfraFailure:
    pass

  try:
    result = get_results(api, load_response.results_dir)
    display_results_summary(api, result)
  # When result parsing fails we want to explicitly return a failure via output
  # properties rather than have the recipe fail with no output properties.
  except api.step.InfraFailure:
    result = _default_failed_result()
  save_state(api, config=properties.config,
             results_dir=load_response.results_dir,
             dut_hostname=dut_hostname, dut_id=envvars.SKYLAB_DUT_ID,
             dut_state=result.state_update.dut_state)
  set_output_properties(api, result=result)


def GenTests(api):
  yield (api.test('test_name_missing') + #
         api.properties(TestRunnerProperties(request={'test': {}})) + #
         api.expect_exception('ValueError'))

  yield (api.test('minimal_end-to-end') + #
         api.properties(TestRunnerProperties(request={
             'test': {'autotest': {'name': 'dummy_name'}}})) + #
         api.properties.environ(TestRunnerEnvProperties(
             SWARMING_BOT_ID='crossk-dummy',
             # TODO(zamorzaev): add a detailed end-to-end test
             # SWARMING_TASK_ID='dummy-task-id',
             # SKYLAB_DUT_ID='dummy-dut-id'
         )) + #
         api.step_data(
             'load local DUT state.call `skylab_local_state`.load',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     skylab_local_state.load.LoadResponse(
                         results_dir='dummy-results-dir')
         )))
        )

  yield (api.test('prejob_crash') + #
         api.properties(TestRunnerProperties(request={
             'test': {'autotest': {'name': 'dummy_name'}}})) + #
         api.properties.environ(TestRunnerEnvProperties(
             SWARMING_BOT_ID='crossk-dummy',
         )) + #
         api.step_data(
           'load local DUT state.call `skylab_local_state`.load',
           stdout=api.raw_io.output(
               json_format.MessageToJson(
                   skylab_local_state.load.LoadResponse(
                   results_dir='dummy-results-dir')
         ))) + #
         api.step_data(
             'run prejob.call `phosphorus`.prejob',
             retcode=1
         )
        )

  yield (api.test('run_test_crash') + #
         api.properties(TestRunnerProperties(request={
             'test': {'autotest': {'name': 'dummy_name'}}})) + #
         api.properties.environ(TestRunnerEnvProperties(
             SWARMING_BOT_ID='crossk-dummy',
         )) + #
         api.step_data(
           'load local DUT state.call `skylab_local_state`.load',
           stdout=api.raw_io.output(
               json_format.MessageToJson(
                   skylab_local_state.load.LoadResponse(
                   results_dir='dummy-results-dir')
         ))) + #
         api.step_data(
             'run test.call `phosphorus`.run-test',
             retcode=1
         )
        )

  yield (api.test('upload_to_tko_crash') + #
         api.properties(TestRunnerProperties(request={
             'test': {'autotest': {'name': 'dummy_name'}}})) + #
         api.properties.environ(TestRunnerEnvProperties(
             SWARMING_BOT_ID='crossk-dummy',
         )) + #
         api.step_data(
           'load local DUT state.call `skylab_local_state`.load',
           stdout=api.raw_io.output(
               json_format.MessageToJson(
                   skylab_local_state.load.LoadResponse(
                   results_dir='dummy-results-dir')
         ))) + #
         api.step_data(
             'upload to TKO.call `phosphorus`.upload-to-tko',
             retcode=1
         )
        )


  yield (api.test('get_results_crash') + #
         api.properties(TestRunnerProperties(request={
             'test': {'autotest': {'name': 'dummy_name'}}})) + #
         api.properties.environ(TestRunnerEnvProperties(
             SWARMING_BOT_ID='crossk-dummy',
         )) + #
         api.step_data(
           'load local DUT state.call `skylab_local_state`.load',
           stdout=api.raw_io.output(
               json_format.MessageToJson(
                   skylab_local_state.load.LoadResponse(
                   results_dir='dummy-results-dir')
         ))) + #
         api.step_data(
             'get test results.call `autotest_status_parser`.parse',
             retcode=1
         )
        )

  yield (api.test('results_summary') + #
         api.properties(TestRunnerProperties(request={
             'test': {'autotest': {'name': 'dummy_name'}}})) + #
         api.properties.environ(TestRunnerEnvProperties(
             SWARMING_BOT_ID='crossk-dummy',
         )) + #
         api.step_data(
             'load local DUT state.call `skylab_local_state`.load',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     skylab_local_state.load.LoadResponse(
                         results_dir='dummy-results-dir')
         ))) + #
         api.step_data(
             'get test results.call `autotest_status_parser`.parse',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     Result(
                         prejob=Result.Prejob(
                             step=[
                                 Result.Prejob.Step(
name='failing_prejob_step',
human_readable_summary='a failing prejob step summary',
verdict=Result.Prejob.Step.VERDICT_FAIL
                            )]
                        ),
autotest_result=Result.Autotest(
    test_cases=[Result.Autotest.TestCase(
        name='failing_test_case',
        human_readable_summary='a failing test case summary',
        verdict=Result.Autotest.TestCase.VERDICT_FAIL
    )]
),
         ))))
        )
