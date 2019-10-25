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
  EnumerationRequest, EnumerationRequests
from PB.test_platform.steps.enumeration import \
  EnumerationResponse, EnumerationResponses
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequest, SchedulerTrafficSplitRequests
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitResponse, SchedulerTrafficSplitResponses
from PB.test_platform.steps.execution import ExecuteRequest, ExecuteRequests
from PB.test_platform.steps.execution import ExecuteResponse, ExecuteResponses
from PB.test_platform.request import Request
from PB.test_platform.taskstate import TaskState
from PB.test_platform.config.config import Config

import collections
import contextlib
import json

from google.protobuf import json_format

from recipe_engine.post_process import GetBuildProperties

DEPS = [
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_test_platform'
]

PROPERTIES = CrosTestPlatformProperties


def enumerate_tests(api, requests):
  """Resolve request into list of tests and their metadata.

  Args:
    * api (object): See RunSteps documentation.
    * requests: {tag: test_platform.Request} dict.

  Returns: {tag: EnumerationResponse} dict.
  """
  with api.step.nest('enumerate tests') as step:
    tags, requests = _unzip_dict(requests)
    enum_requests = EnumerationRequests(requests=[
        EnumerationRequest(
            metadata=r.params.metadata,
            test_plan=r.test_plan,
        )
        for r in requests
    ])
    responses = api.cros_test_platform.enumerate(enum_requests)
    responses = _zip_to_dict(tags, responses.responses)
    for tag, response in responses.iteritems():
      name = 'autotest tests for %s' % tag
      step.presentation.logs[name] = _enumeration_log(response)
    return responses


def _enumeration_log(response):
  """Compute lines to log for the given test_platform.EnumerationResponses."""
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


def split(api, requests, config):
  """Determine which backend will execute the request.

  Args:
    * api (object): See RunSteps documentation.
    * requests: {tag: test_platform.Request} dict.
    * config: test_platform.Config instance.

  Returns: bool, [test_platform.Request]
    * First item in the pair indicates whether this is a skylab request.
    * Second item in the pair is {tag: test_platform.Request} dict of extracted
          requests.
  """
  with api.step.nest('traffic split') as step:
    tags, requests = _unzip_dict(requests)
    split_req = SchedulerTrafficSplitRequests(
      requests=[
        SchedulerTrafficSplitRequest(
          request=r,
          config=config.scheduler_migration,
        )
        for r in requests
      ],
    )
    split_resp = api.cros_test_platform.scheduler_traffic_split(split_req)
    is_skylab, requests = _get_backend_requests(split_resp.responses)
    env_name = 'skylab' if is_skylab else 'autotest'
    step.presentation.step_summary_text = 'selected backend: ' + env_name
    return is_skylab, _zip_to_dict(tags, requests)


def _unzip_dict(d):
  """Unzips given dict two equal sized lists."""
  pairs = [(k, v) for k, v in d.iteritems()]
  return zip(*pairs)


def _zip_to_dict(ks, vs):
  """Zips two equal sized lists to a dict."""
  if len(ks) != len(vs):
    raise ValueError("Got %d values for %d keys"
                     % (len(vs), len(ks)))
  return {k: v for k, v in  zip(ks, vs)}


def _get_backend_requests(split_responses):
  """Extract the backend request from traffic splitter response.

  Args:
    * split_resp: A test_platform.SchedulerTrafficSplitResponse object.

  Returns: bool, [test_platform.Request]
    * First item in the pair indicates whether this is a skylab request.
    * Second item in the pair is the list of extracted requests.
  """
  is_first_skylab, request = _get_backend_request(split_responses[0])
  requests = [request]
  for response in split_responses[1:]:
    is_skylab, request = _get_backend_request(response)
    if is_first_skylab != is_skylab:
      raise ValueError('Traffic splits contain both autotest and skylab'
                       ' across requests; this is not supported.')
    requests.append(request)
  return is_first_skylab, requests


def _get_backend_request(split_resp):
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


def execute(api, requests, enumerations, config, use_skylab):
  """Execute request in the correct backend.

  Args:
    requests: {tag: test_platform.Request} dict.
    enumerations: {tag: EnumerationResponse} dict.
    config: test_platform.Config instance.
    use_skylab: bool indicating which backend to run in
                (True -> skylab, False -> autotest).
  """
  with api.step.nest('execute'):
    tags, requests = _unzip_dict(requests)
    _, enumerations = _unzip_dict(enumerations)
    exec_reqs = ExecuteRequests(requests=[
        ExecuteRequest(request_params=r.params, enumeration=e, config=config)
        for r, e in zip(requests, enumerations)
    ])
    if use_skylab:
      responses = api.cros_test_platform.skylab_execute(exec_reqs)
    else:
      responses = api.cros_test_platform.autotest_execute(exec_reqs)
    return _zip_to_dict(tags, responses.responses)


def RunSteps(api, properties):
  requests = _get_requests_from_properties(properties)
  # Traffic split failures can be due to malformed requests.
  skylab, requests = split(api, requests, properties.config)

  # Enumeration or execution failures are all infra failures
  # TODO(akeshet) (with the possible exception of certain kinds of execution
  # timeouts; needs revisiting).
  with api.context(infra_steps=True):
    enumerations = enumerate_tests(api, requests)
    responses = execute(api, requests, enumerations, properties.config, skylab)

  # Failures in summarization are non-infra related.
  with api.step.nest('summarize') as step:
    # TODO(crbug.com/1008134) Set responses property instead when applicable.
    _set_output_properties(step, responses)
    for tag, response in responses.iteritems():
      with api.step.nest('%s task results' % tag):
        _log_task_results(api, response.task_results)


def _get_requests_from_properties(properties):
  if len(properties.requests) > 0:
    if properties.HasField('request'):
      raise ValueError('Must set only one of request and requests')
    return properties.requests
  if properties.HasField('request'):
    return {
      'default': properties.request,
    }
  raise ValueError('Must set at least one of request and requests')


def _set_output_properties(step, responses):
  """Set the builder 'response' property from test_platform.ExecuteResponse."""
  marshalled = {}
  for tag, response in responses.iteritems():
    marshalled[tag] = _marshal_response_to_json(response)
  step.properties['responses'] = marshalled
  if 'default' in marshalled:
    step.properties['response'] = marshalled['default']


def _marshal_response_to_json(response):
  # The `response` field of CrosTestPlatformProperties is a message of
  # type ExecuteResponse. However, the recipe-supported mechanism for setting
  # output properties supports only json-encodable python structures, not
  # protos, so roundtrip the actual ExecuteResponse proto through json.
  return json.loads(json_format.MessageToJson(response))


def _log_task_results(api, task_results):
  """Report task results for a request on the UI."""
  # TODO(akeshet): Don't present failure if the underlying enumeration item
  # was retried and passed separately. Instead, include in a "failed but
  # retried" section.
  classified_results = _classify_task_results(task_results)
  if classified_results.passed:
    with api.step.nest('passed tests') as step:
      _emit_links(step, classified_results.passed)
  if classified_results.passed_on_retry:
    with api.step.nest('failed attempts that later passed') as step:
      _emit_links(step, classified_results.passed_on_retry)
  if classified_results.unsuccessful:
    with _failing_substep(api, 'failed or incomplete tests') as step:
      _emit_links(step, classified_results.unsuccessful)
  if classified_results.rejected:
    with _failing_substep(api, 'tests rejected due to invalid request') as step:
      _emit_links(step, classified_results.rejected)
  if classified_results.other:  # pragma: no cover
    with _failing_substep(api, 'unclassified tests') as step:
      _emit_links(step, classified_results.other)

  if _contains_unsuccessful_results(classified_results):
    raise api.step.StepFailure('Some tests were unsuccessful')


_ClassifiedTaskResults = collections.namedtuple(
    '_ClassifiedTaskResults',
    ['passed', 'passed_on_retry', 'unsuccessful', 'rejected', 'other'],
)


def _classify_task_results(task_results):
  classified = _ClassifiedTaskResults(passed=[], passed_on_retry=[],
                                      unsuccessful=[], rejected=[], other=[])
  d = collections.defaultdict(bool)
  failed_tasks = []
  for tr in task_results:
    # The order of these guard clauses is significant
    if (tr.state.verdict == TaskState.VERDICT_PASSED or
        tr.state.verdict == TaskState.VERDICT_PASSED_ON_RETRY):
      d[tr.name] = (tr.state.verdict == TaskState.VERDICT_PASSED_ON_RETRY)
      classified.passed.append(tr)
    elif tr.state.life_cycle == TaskState.LIFE_CYCLE_REJECTED:
      classified.rejected.append(tr)
    elif tr.state.verdict in (TaskState.VERDICT_FAILED,
                              TaskState.VERDICT_UNSPECIFIED):
      failed_tasks.append(tr)
    else:  # pragma: no cover
      classified.other.append(tr)

  for tr in failed_tasks:
    if d[tr.name]:
      classified.passed_on_retry.append(tr)
    else:
      classified.unsuccessful.append(tr)

  return classified


def _contains_unsuccessful_results(classified_results):
  return (classified_results.unsuccessful or classified_results.rejected or
          classified_results.other)


@contextlib.contextmanager
def _failing_substep(api, tag):
  try:
    with api.step.nest(tag) as step:
      yield step
      raise api.step.StepFailure(tag)
  except api.step.StepFailure:
    pass


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
    suffix = ''
    if t.attempt > 0:
      suffix = ' attempt #%s' % str(t.attempt)
      if (t.state.verdict == TaskState.VERDICT_PASSED_ON_RETRY or
          t.state.verdict == TaskState.VERDICT_PASSED):
        suffix = suffix + ' passed on retry'
    step.links['(log)   ' + t.name + suffix] = t.log_url
    step.links['(task)  ' + t.name + suffix] = t.task_url


def GenTests(api):
  # Missing request and requests should cause a recipe crash
  yield (
    api.test('no request or requests') + #
    api.expect_exception("ValueError")
  )

  # Setting both request and requests should cause a recipe crash
  yield (
    api.test('both request and requests') + #
    api.properties(CrosTestPlatformProperties(
        request=Request(),
        requests={'first': Request()},
    )) + #
    api.expect_exception("ValueError")
  )

  # Traffic split with no traffic to either autotest or skylab
  # should cause recipe crash.
  no_traffic_split = SchedulerTrafficSplitResponses(responses=[
      SchedulerTrafficSplitResponse()
  ])
  no_traffic_split_json = json_format.MessageToJson(no_traffic_split)
  yield (
    api.test('no traffic') + #
    api.properties(CrosTestPlatformProperties(request=Request())) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
    stdout=api.raw_io.output(no_traffic_split_json)) + #
    api.expect_exception("ValueError")
  )

  # Traffic split with traffic to both autotest and skylab
  # should cause recipe crash.
  dual_traffic_split = SchedulerTrafficSplitResponses(responses=[
      SchedulerTrafficSplitResponse(
          autotest_request=Request(
              test_plan=Request.TestPlan(suite=[Request.Suite(name="foo")]),),
          skylab_request=Request(
              test_plan=Request.TestPlan(suite=[Request.Suite(name="foo")]),),
      )
  ])
  dual_traffic_split_json = json_format.MessageToJson(dual_traffic_split)
  yield (
    api.test('dual traffic') + #
    api.properties(CrosTestPlatformProperties(request=Request())) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
    stdout=api.raw_io.output(dual_traffic_split_json)) + #
    api.expect_exception("ValueError")
  )

  # Traffic split with traffic to both autotest and skylab in different requests
  # should cause recipe crash.
  dual_traffic_split_requests = SchedulerTrafficSplitResponses(responses=[
      SchedulerTrafficSplitResponse(
          autotest_request=Request(
              test_plan=Request.TestPlan(suite=[Request.Suite(name="foo")]),),
      ),
      SchedulerTrafficSplitResponse(
          skylab_request=Request(
              test_plan=Request.TestPlan(suite=[Request.Suite(name="foo")]),),
      )
  ])
  yield (
    api.test('dual traffic across requests') + #
    api.properties(CrosTestPlatformProperties(request=Request())) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
    stdout=api.raw_io.output(
      json_format.MessageToJson(dual_traffic_split_requests))) + #
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
  e2e_split_response_skylab = SchedulerTrafficSplitResponses(responses=[
      SchedulerTrafficSplitResponse(skylab_request=e2e_request)
  ])
  # Note: using raw JSON here to avoid needing to import the chromite
  # protos.
  e2e_enumeration_responses = """
  {
    "responses": [
      {
        "autotest_invocations": [{"test": {"name": "foo-test"}}]
      }
    ]
  }"""
  e2e_execute_responses_passed = ExecuteResponses(responses=[
      ExecuteResponse(
          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                          verdict='VERDICT_PASSED'),
          task_results=[
              ExecuteResponse.TaskResult(
                  task_url='foo://bar/baz',
                  log_url='logs://bar/baz',
                  name='foo-passed',
                  state=TaskState(verdict="VERDICT_PASSED"),
              ),
          ],
      )
  ])
  yield (
    api.test('end-to-end skylab execution with passed tasks') + #
    api.properties(CrosTestPlatformProperties(request=e2e_request,
                                              config=e2e_config)) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_split_response_skylab))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output(e2e_enumeration_responses)) + #
    api.step_data('execute.call binary.skylab-execute',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_execute_responses_passed)))
  )

  e2e_execute_responses_failed = ExecuteResponses(responses=[
      ExecuteResponse(
          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                          verdict='VERDICT_FAILED'),
          task_results=[
              ExecuteResponse.TaskResult(
                  task_url='foo://bar/baz',
                  log_url='logs://bar/baz',
                  name='foo-failed',
                  state=TaskState(verdict="VERDICT_FAILED"),
              ),
              ExecuteResponse.TaskResult(
                  task_url='foo://bar/baz1',
                  log_url='logs://bar/baz1',
                  name='foo-failed',
                  attempt=1,
                  state=TaskState(verdict="VERDICT_FAILED"),
              ),
          ],
      )
  ])
  yield (
    api.test('end-to-end skylab execution with failed tasks') + #
    api.properties(CrosTestPlatformProperties(request=e2e_request,
                                              config=e2e_config)) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_split_response_skylab))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output(e2e_enumeration_responses)) + #
    api.step_data('execute.call binary.skylab-execute',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_execute_responses_failed)))
  )

  e2e_execute_responses_retried = ExecuteResponses(responses=[
      ExecuteResponse(
          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                          verdict='VERDICT_PASSED_ON_RETRY'),
          task_results=[
              ExecuteResponse.TaskResult(
                  task_url='foo://bar/baz',
                  log_url='logs://bar/baz',
                  name='foo-retried',
                  state=TaskState(verdict="VERDICT_FAILED"),
              ),
              ExecuteResponse.TaskResult(
                  task_url='foo://bar/baz1',
                  log_url='logs://bar/baz1',
                  name='foo-retried',
                  attempt=1,
                  state=TaskState(verdict="VERDICT_PASSED_ON_RETRY"),
              ),
          ],
      )
  ])
  yield (api.test('end-to-end skylab execution with retried tasks') +  #
         api.properties(
             CrosTestPlatformProperties(request=e2e_request, config=e2e_config))
         +  #
         api.step_data(
             'traffic split.call binary.scheduler-traffic-split',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(e2e_split_response_skylab))) +  #
         api.step_data('enumerate tests.call binary.enumerate',
                       stdout=api.raw_io.output(e2e_enumeration_responses)) +  #
         api.step_data(
             'execute.call binary.skylab-execute', stdout=api.raw_io.output(
                 json_format.MessageToJson(e2e_execute_responses_retried))))

  e2e_execute_responses_rejected = ExecuteResponses(responses=[
      ExecuteResponse(
          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                          verdict='VERDICT_FAILED'),
          task_results=[
              ExecuteResponse.TaskResult(
                  task_url='foo://bar/baz',
                  log_url='logs://bar/baz',
                  name='foo-rejected',
                  state=TaskState(life_cycle="LIFE_CYCLE_REJECTED"),
              ),
          ],
      )
  ])
  yield (
    api.test('end-to-end skylab execution with rejected tasks') + #
    api.properties(CrosTestPlatformProperties(request=e2e_request,
                                              config=e2e_config)) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_split_response_skylab))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output(e2e_enumeration_responses)) + #
    api.step_data('execute.call binary.skylab-execute',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_execute_responses_rejected)))
  )

  # An end-to-end run with traffic splitting to autotest.
  e2e_split_response_autotest = SchedulerTrafficSplitResponses(responses=[
      SchedulerTrafficSplitResponse(autotest_request=e2e_request)
  ])
  yield (
    api.test('end-to-end with autotest execution') + #
    api.properties(CrosTestPlatformProperties(request=e2e_request,
                                              config=e2e_config)) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_split_response_autotest))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output(e2e_enumeration_responses)) + #
    api.step_data('execute.call binary.autotest-execute',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_execute_responses_passed)))
  )

  too_many_split_responses =  SchedulerTrafficSplitResponses(responses=[
      SchedulerTrafficSplitResponse(autotest_request=e2e_request),
      SchedulerTrafficSplitResponse(autotest_request=e2e_request)
  ])
  yield (
    api.test('too many traffic splitter responses') + #
    api.properties(CrosTestPlatformProperties(request=e2e_request,
                                              config=e2e_config)) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(too_many_split_responses))) + #
    api.expect_exception("ValueError")
  )

  # TODO(pprabhu) Verify that responses is set.
  e2e_multi_build_responses = {
      'first': json_format.MessageToJson(e2e_execute_responses_passed),
  }
  yield (
    api.test('end-to-end multi-requests with skylab execution') + #
    api.properties(CrosTestPlatformProperties(
        requests={'first': e2e_request},
        config=e2e_config,
    )) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(e2e_split_response_skylab))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output(e2e_enumeration_responses)) + #
    api.step_data(
      'execute.call binary.skylab-execute',
      stdout=api.raw_io.output(
          json_format.MessageToJson(e2e_execute_responses_passed))) + #
    # api.post_process(PropertyEquals, 'responses', e2e_multi_build_responses)
    api.post_check(lambda check, steps: check(
        len(GetBuildProperties(steps).get('responses', {})) > 0))
  )
