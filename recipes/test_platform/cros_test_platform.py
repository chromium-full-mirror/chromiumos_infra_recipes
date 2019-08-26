# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Test Frontend.

TODO: Migrate to a recipes repo owned by the test team.
"""

from PB.recipes.chromeos.test_platform.cros_test_platform import \
  CrosTestPlatformProperties
from PB.test_platform.steps.enumeration import \
  EnumerationRequest, EnumerationResponse
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequest, SchedulerTrafficSplitResponse
from PB.test_platform.steps.execution import ExecuteRequest, ExecuteResponse
from PB.test_platform.request import Request
from PB.test_platform.taskstate import TaskState
from PB.test_platform.config.config import Config

import json

from google.protobuf import json_format

DEPS = [
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_test_platform'
]

PROPERTIES = CrosTestPlatformProperties


def enumerate_tests(api, request):
  """Resolve request into list of tests and their metadata.

  Args:
    * api (object): See RunSteps documentation.
    * request: test_platform.Request instance.

  Returns: EnumerationResponse.
  """
  with api.step.nest('enumerate tests') as step:
    enum_request = EnumerationRequest(
      metadata=request.params.metadata,
      test_plan=request.test_plan,
    )
    response = api.cros_test_platform.enumerate(enum_request)
    log_lines = [_enumerate_log(x) for x in response.autotest_invocations]
    step.presentation.logs['autotest tests'] = log_lines
    return response


def _enumerate_log(autotest_invocation):
  """Returns a 1-line string logging representation of an enumerated test.

  Args:
    * autotest_invocation: AutotestInvocation instance.

  Returns:
    * string logging representation.
  """
  # Note: At some point, consider adding other fields to this log, such as
  # the test's declared dependencies, as defined by the AutotestTest proto.
  return autotest_invocation.test.name


def split(api, request, config):
  """Determine which backend will execute the request.

  Args:
    * api (object): See RunSteps documentation.
    * request: test_platform.Request instance.
    * config: test_platform.Config instance.

  Returns: (test_platform.Request, bool (skylab)) tuple.
  """
  with api.step.nest('traffic split') as step:
    split_req = SchedulerTrafficSplitRequest(
      request=request,
      config=config.scheduler_migration,
    )
    split_resp = api.cros_test_platform.scheduler_traffic_split(split_req)

    autotest_request = split_resp.autotest_request
    skylab_request = split_resp.skylab_request
    # Rely on ByteSize of protos to determine which message is nonempty.
    has_autotest = bool(autotest_request.ByteSize())
    has_skylab = bool(skylab_request.ByteSize())
    if has_autotest and has_skylab:
      raise ValueError('Traffic splits contains both autotest and skylab '
                       'components; this is not supported.')
    if not (has_autotest or has_skylab):
      raise ValueError('Traffic split contains no traffic for either autotest '
                       'or skylab.')

    env_name = 'skylab' if has_skylab else 'autotest'
    step.presentation.step_summary_text = 'selected backend: ' + env_name

    request = skylab_request if has_skylab else autotest_request
    return request, has_skylab


def execute(api, request, enumeration, config, use_skylab):
  """Execute request in the correct backend.

  Args:
    request: test_platform.Request instance.
    enumeration: EnumerationResponse instance.
    config: test_platform.Config instance.
    use_skylab: bool indicating which backend to run in
                (True -> skylab, False -> autotest).
  """
  with api.step.nest('execute'):
    exec_req = ExecuteRequest(
      request_params=request.params,
      enumeration=enumeration,
      config=config
    )
    if use_skylab:
      return api.cros_test_platform.skylab_execute(exec_req)
    else:
      return api.cros_test_platform.autotest_execute(exec_req)


def RunSteps(api, properties):
  # Traffic split failures can be due to malformed requests.
  request, skylab = split(api, properties.request, properties.config)

  # Enumeration or execution failures are all infra failures
  # TODO(akeshet) (with the possible exception of certain kinds of execution
  # timeouts; needs revisiting).
  with api.context(infra_steps=True):
    enumeration = enumerate_tests(api, request)
    resp = execute(api, request, enumeration, properties.config, skylab)

  # Failures in summarization are non-infra related.
  with api.step.nest('summarize') as step:
    # The `response` field of CrosTestPlatformProperties is a message of
    # type ExecuteResponse. However, the recipe-supported mechanism for setting
    # output properties supports only json-encodable python structures, not
    # protos, so roundtrip the actual ExecuteResponse proto through json.
    step.properties['response'] = json.loads(json_format.MessageToJson(resp))

    with api.step.nest('passed tests') as step:
      passed_tests = [x for x in resp.task_results
                      if x.state.verdict == TaskState.VERDICT_PASSED]
      _emit_links(step.links, passed_tests)
    with api.step.nest('failed tests') as step:
      failed_tests = [x for x in resp.task_results
                      if x.state.verdict == TaskState.VERDICT_FAILED]
      _emit_links(step.links, failed_tests)
      if failed_tests:
        raise api.step.StepFailure('tests failed')
    # TODO(akeshet): Handle task links for verdictless tasks (including
    # incomplete tasks and completed tasks which provide no verdict).


def _emit_links(links, tasks):
  """Emit presentation links related to a task.

  Args:
    * links: a step.presentation.links instance.
    * tasks: a list of TaskResult instances.
  """
  # TODO(akeshet): Correctly handle link emission in the case of multiple
  # task results with the same name. This will involve a proto change that
  # includes attempt number in the result.
  for t in tasks:
    links['(log)   ' + t.name] = t.log_url
    links['(task)  ' + t.name] = t.task_url



def GenTests(api):
  # Traffic split with no traffic to either autotest or skylab
  # should cause recipe crash.
  yield (
    api.test('no traffic') + #
    api.expect_exception("ValueError")
  )

  # Traffic split with traffic to both autotest and skylab
  # should cause recipe crash.
  dual_traffic_split = SchedulerTrafficSplitResponse(
    autotest_request=Request(
      test_plan=Request.TestPlan(
        suite=[Request.Suite(name="foo")]
      ),
    ),
    skylab_request=Request(
      test_plan=Request.TestPlan(
        suite=[Request.Suite(name="foo")]
      ),
    ),
  )
  dual_traffic_split_json = json_format.MessageToJson(dual_traffic_split)
  yield (
    api.test('dual traffic') + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
    stdout=api.raw_io.output(dual_traffic_split_json)) + #
    api.expect_exception("ValueError")
  )

  # An end-to-end run with traffic splitting to skylab.
  e2e_request = Request(
    params=Request.Params(
      hardware_attributes=Request.Params.HardwareAttributes(
        model='foo-model'
      ),
      metadata=Request.Params.Metadata(
        test_metadata_url="foo-metadata-url"
      )
    ),
    test_plan=Request.TestPlan(
      suite=[Request.Suite(name="foo-suite")]
    ),
  )
  e2e_config = Config(
    skylab_worker=Config.SkylabWorker(
      luci_project='foo luci project'
    ),
    scheduler_migration=Config.SchedulerMigration(
      gitiles_host='foo gitiles host'
    ),
  )
  e2e_split_response_skylab = SchedulerTrafficSplitResponse(
    skylab_request=e2e_request
  )
  e2e_execute_response = ExecuteResponse(
    state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                    verdict='VERDICT_PASSED'),
    task_results=[
      ExecuteResponse.TaskResult(
        task_url='foo://bar/baz',
        log_url='logs://bar/baz',
        name='foo-passed',
        state=TaskState(verdict="VERDICT_PASSED"),
      ),
      ExecuteResponse.TaskResult(
        task_url='foo://bar/baz',
        log_url='logs://bar/baz',
        name='foo-failed',
        state=TaskState(verdict="VERDICT_FAILED"),
      ),
    ],
  )
  # Note: using raw JSON here to avoid needing to import the chromite
  # protos.
  e2e_enumeration_response = """
  {
    "autotest_invocations": [{"test": {"name": "foo-test"}}]
  }
    """
  yield (
    api.test('end-to-end with skylab execution') + #
    api.properties(CrosTestPlatformProperties(request=e2e_request,
                                              config=e2e_config)) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_split_response_skylab))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output(e2e_enumeration_response)) + #
    api.step_data('execute.call binary.skylab-execute',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_execute_response)))
  )

  # An end-to-end run with traffic splitting to autotest.
  e2e_split_response_autotest = SchedulerTrafficSplitResponse(
    autotest_request=e2e_request
  )
  yield (
    api.test('end-to-end with autotest execution') + #
    api.properties(CrosTestPlatformProperties(request=e2e_request,
                                              config=e2e_config)) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_split_response_autotest))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output(e2e_enumeration_response)) + #
    api.step_data('execute.call binary.autotest-execute',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_execute_response)))
  )