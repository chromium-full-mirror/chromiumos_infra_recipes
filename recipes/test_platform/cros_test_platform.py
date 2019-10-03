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
    step.presentation.logs['autotest tests'] = _enumeration_log(response)
    return response


def _enumeration_log(response):
  """Compute lines to log for the given test_platform.EnumerationResponse."""
  return [_invocation_summary(x) for x in response.autotest_invocations]


def _invocation_summary(autotest_invocation):
  """Returns a 1-line string summary of an enumerated test.

  Args:
    * autotest_invocation: AutotestInvocation instance.

  Returns: A short summary string.
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
    is_skylab, request = _get_backend_request(split_resp)
    env_name = 'skylab' if is_skylab else 'autotest'
    step.presentation.step_summary_text = 'selected backend: ' + env_name
    return request, is_skylab


def _get_backend_request(split_resp):
  """Extract the backend request from traffic splitter response.

  Args:
    * split_resp: A test_platform.SchedulerTrafficSplitResponse object.

  Returns: bool, test_platform.Request
    * First item in the pair indicates whether this is a skylab request.
    * Second item in the pair is the extracted request.
  """
  autotest = split_resp.autotest_request
  skylab = split_resp.skylab_request
  is_skylab = _is_non_empty_proto(skylab)
  if is_skylab and _is_non_empty_proto(autotest):
    raise ValueError('Traffic splits contains both autotest and skylab '
                     'components; this is not supported.')
  if not is_skylab and not _is_non_empty_proto(autotest):
    raise ValueError('Traffic split contains no traffic for either autotest '
                     'or skylab.')
  request = skylab if is_skylab else autotest
  return is_skylab, request


def _is_non_empty_proto(p):
  return bool(p.ByteSize())


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
    response = execute(api, request, enumeration, properties.config, skylab)

  # Failures in summarization are non-infra related.
  with api.step.nest('summarize') as step:
    _set_response_property(step, response)
    _log_task_results(api, response.task_results)


def _set_response_property(step, response):
  """Set the builder 'response' property from test_platform.ExecuteResponse."""
  # The `response` field of CrosTestPlatformProperties is a message of
  # type ExecuteResponse. However, the recipe-supported mechanism for setting
  # output properties supports only json-encodable python structures, not
  # protos, so roundtrip the actual ExecuteResponse proto through json.
  step.properties['response'] = json.loads(json_format.MessageToJson(response))


def _log_task_results(api, task_results):
  """Report task results for a request on the UI."""
  # TODO(akeshet): Don't present failure if the underlying enumeration item
  # was retried and passed separately. Instead, include in a "failed but
  # retried" section.
  # TODO(akeshet): Handle task links for verdictless tasks (including
  # incomplete tasks and completed tasks which provide no verdict).
  with api.step.nest('passed tests') as step:
    _emit_links(step, _filter_successful_task_results(task_results))
  with api.step.nest('failed or incomplete tests') as step:
    unsuccessful_task_results = _filter_unsuccessful_task_results(task_results)
    _emit_links(step, unsuccessful_task_results)
    if unsuccessful_task_results:
      raise api.step.StepFailure('tests failed')


def _filter_successful_task_results(task_results):
  return [x for x in task_results
          if x.state.verdict == TaskState.VERDICT_PASSED]


_UNSUCCESSFUL_VERDICTS = (
  TaskState.VERDICT_FAILED,
  TaskState.VERDICT_UNSPECIFIED,
)


def _filter_unsuccessful_task_results(task_results):
  return [x for x in task_results if x.state.verdict in _UNSUCCESSFUL_VERDICTS]


def _emit_links(step, task_results):
  """Emit presentation links related to a task.

  Args:
    * step:  a recipe step.
    * task_results: a list of TaskResult instances.
  """
  # TODO(akeshet): Correctly handle link emission in the case of multiple
  # task results with the same name. This will involve a proto change that
  # includes attempt number in the result.
  for t in task_results:
    step.links['(log)   ' + t.name] = t.log_url
    step.links['(task)  ' + t.name] = t.task_url


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
