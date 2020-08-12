# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Test Frontend.

TODO: Migrate to a recipes repo owned by the test team.
"""

from PB.chromite.api import test_metadata
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipes.chromeos.test_platform.cros_test_platform import \
  CrosTestPlatformProperties
from PB.recipes.chromeos.test_platform.cros_test_postprocess import \
  CrosTestPostprocessRequest
from PB.recipes.chromeos.test_platform.cros_test_postprocess import \
  TestResult as PostProcessTestResult
from PB.test_platform import result_flow as result_flow_pb2
from PB.test_platform.steps.enumeration import \
  EnumerationRequest, EnumerationRequests
from PB.test_platform.steps.enumeration import \
  EnumerationResponse, EnumerationResponses
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitRequest, SchedulerTrafficSplitRequests
from PB.test_platform.steps.scheduler_traffic_split import \
  SchedulerTrafficSplitResponse, SchedulerTrafficSplitResponses
from PB.test_platform import migration
from PB.test_platform.steps import enumeration
from PB.test_platform.steps.execution import ExecuteRequest, ExecuteRequests
from PB.test_platform.steps.execution import ExecuteResponse, ExecuteResponses
from PB.test_platform.request import Request
from PB.test_platform.taskstate import TaskState
from PB.test_platform.config.config import Config
from PB.test_platform.steps.execute.build import Build

import collections
import contextlib
import json

from google.protobuf import duration_pb2
from google.protobuf import json_format

from recipe_engine.post_process import GetBuildProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/random',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'result_flow',
    'cros_test_platform',
]

PROPERTIES = CrosTestPlatformProperties


def validate_requests(api, requests):
  validation_errors = []
  with api.step.nest('validate request') as step:
    validation_errors.append(_validate_timeouts(api, requests))
    validation_errors.append(_validate_scheduling_params(api, requests))
  if any(validation_errors):
    raise api.step.StepFailure('request validation failed')


def _validate_timeouts(api, requests):
  """Validate timeouts in the requests.

  Returns: True if requests are valid, False otherwise.
  """
  validation_error = False
  with api.step.nest('validate timeouts') as step:
    max_timeout = api.buildbucket.build.execution_timeout
    max_timeout_s = max_timeout.ToTimedelta().total_seconds()
    for t, r in requests.iteritems():
      request_timeout = r.params.time.maximum_duration
      if request_timeout is None:
        continue  # pragma: no cover

      request_timeout_s = request_timeout.ToTimedelta().total_seconds()
      if request_timeout_s > 0 and request_timeout_s >= max_timeout_s:
        step.presentation.logs[t] = [
            'Timeout (%s) is larger than maximum timeout (%s)' %
            (request_timeout.ToTimedelta(), max_timeout.ToTimedelta())
        ]
        step.presentation.status = api.step.FAILURE
        validation_error = True
  return validation_error


def _validate_scheduling_params(api, requests):
  """Validate scheduling parameters in the requests.

  Returns: True if requests are valid, False otherwise.
  """
  validation_error = False
  with api.step.nest('validate scheduling parameters') as step:
    for t, r in requests.iteritems():
      error = _get_scheduling_error(api, r)
      if error:
        validation_error = True
        step.presentation.logs[t] = [error]
        step.presentation.status = api.step.FAILURE
  return validation_error


def _get_scheduling_error(api, request):
  qs_account = request.params.scheduling.qs_account
  priority = request.params.scheduling.priority
  # Requests for which the pool is overridden downstream may have both priority
  # and quota account unset, see crbug.com/1074373.
  if priority:
    if qs_account:
      return ('priority and qs_account should not both be set. ' +
              'Got priority: %d and qs_account: %s' % (priority, qs_account))
    if priority < 50 or priority > 255:
      return ('priority %d is out of valid range [50, 255]' % priority)


def enumerate_tests(api, requests):
  """Resolve request into list of tests and their metadata.

  Args:
    * api (object): See RunSteps documentation.
    * requests: {tag: test_platform.Request} dict.

  Returns: {tag: EnumerationResponse} dict.
  """
  with api.step.nest('enumerate tests') as step:
    enum_requests = EnumerationRequests(
        tagged_requests={
            t: EnumerationRequest(
                metadata=r.params.metadata,
                test_plan=r.test_plan,
            ) for t, r in requests.iteritems()
        })
    enum_responses = api.cros_test_platform.enumerate(enum_requests)
    for tag, response in enum_responses.tagged_responses.iteritems():
      name = 'autotest tests for %s' % tag
      step.presentation.logs[name] = _enumeration_log(response)
    return enum_responses.tagged_responses


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
  """Run the almost no-op traffic splitter step.

  This step now always directs traffic to Skylab.
  TODO(crbug.com/1026367) Completely skip this step once we stop receiving
                          requests for legacy bvt, suites pools.

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
    split_req = SchedulerTrafficSplitRequests(
        tagged_requests={
            tag: SchedulerTrafficSplitRequest(request=r)
            for tag, r in requests.iteritems()
        })
    split_resp = api.cros_test_platform.scheduler_traffic_split(split_req)
    tagged_requests = {
        t: _get_backend_request(r)
        for t, r in split_resp.tagged_responses.iteritems()
    }
    step.presentation.step_summary_text = 'selected backend: skylab'
    return tagged_requests


def _get_backend_request(split_resp):
  if not _is_non_empty_proto(split_resp.skylab_request):
    raise ValueError('Traffic split contains no traffic for any backend.')
  return split_resp.skylab_request


def _is_non_empty_proto(p):
  return bool(p.ByteSize())


def push_build_id(api, config):
  with api.step.nest('publish build ID') as step:
    if api.buildbucket.build.id and config.pubsub.topic and config.pubsub.project:
      api.result_flow.publish(config.pubsub.project, config.pubsub.topic)
    else:
      step.presentation.step_summary_text = (
          'decision: skip pubulishing build ID')


def execute(api, requests, enumerations, config):
  """Execute request in the correct backend.

  Args:
    requests: {tag: test_platform.Request} dict.
    enumerations: {tag: EnumerationResponse} dict.
    config: test_platform.Config instance.
  """
  with api.step.nest('execute'):
    _ensure_all_requests_enumerated(requests, enumerations)
    exec_reqs = ExecuteRequests(
        tagged_requests={
            t: ExecuteRequest(
                request_params=_set_notification(r.params, config),
                enumeration=enumerations[t], config=config)
            for t, r in requests.iteritems()
        },
        build=Build(id=api.buildbucket.build.id,
                    create_time=api.buildbucket.build.create_time),
    )
    return api.cros_test_platform.skylab_execute(exec_reqs)


def _set_notification(params, config):
  """Attach PubSub topic to each ExecuteRequest.

  Returns:
  same test_platform.Request.Params instance of input.
  """
  pubsub = config.test_runner.pubsub
  if pubsub.project and pubsub.topic:
    # The topic attached here is for notifying the cros_test_platform's
    # internal pipeline to process the test runner output.
    params.notification.pubsub_topic = "projects/%s/topics/%s" % (
        pubsub.project, pubsub.topic)
  return params


def _ensure_all_requests_enumerated(requests, enumerations):
  missing = set(requests.keys()) - set(enumerations.keys())
  if missing:
    raise ValueError('No enumerations for requests tagged %s' % missing)


def RunSteps(api, properties):
  requests = _get_requests_from_properties(properties)
  # Push Build ID to Pubsub to notify the subscribers that a new CTP
  # build is about to run.
  push_build_id(api, properties.config)
  validate_requests(api, requests)
  # Traffic split failures can be due to malformed requests.
  requests = split(api, requests, properties.config)
  with api.context(infra_steps=True):
    enumerations = enumerate_tests(api, requests)
    responses = execute(api, requests, enumerations, properties.config)
    tagged_responses = responses.tagged_responses
    set_output_properties(api, responses)
    # Push the Build ID to notify the subscribers that CTP run completed.
    push_build_id(api, properties.config)
    postprocess(api, requests, tagged_responses)
  summarize(api, enumerations, tagged_responses)


def postprocess(api, requests, responses):
  with api.step.nest('postprocess') as step:
    for tag, response in responses.iteritems():
      request = requests[tag]
      if not request.params.metadata.debug_symbols_archive_url:
        continue  # pragma: no cover

      test_results = []
      # TODO(akeshet): Iterate through response.consolidated_results instead of
      # task_results, which is going to be deprecated.
      # Why not do this already? Because consolidated_results population is not
      # yet implemented in the rest of this recipe; in particular, all of the
      # test expectations currently do not set it, so to use it now would
      # result in 0 test coverage within this loop.
      for result in response.task_results:
        if result.state.life_cycle == TaskState.LIFE_CYCLE_COMPLETED:
          test_results.append(PostProcessTestResult(log_data=result.log_data))
      if not test_results:
        continue

      with api.step.nest(tag) as step:
        pp_request = CrosTestPostprocessRequest(
            debug_symbols_archive_url=request.params.metadata
            .debug_symbols_archive_url,
            test_results=test_results,
        )
        bb_request = api.buildbucket.schedule_request(
            bucket='testplatform',
            builder='cros_test_postprocess',
            properties=json_format.MessageToDict(pp_request),
            inherit_buildsets=False,
        )
        api.buildbucket.schedule([bb_request])


_SUCCESSFUL_VERDICTS = (TaskState.VERDICT_PASSED,
                        TaskState.VERDICT_PASSED_ON_RETRY,
                        TaskState.VERDICT_NO_VERDICT)


def summarize(api, enumerations, responses):
  # Failures in summarization are non-infra related.
  with api.step.nest('summarize') as step:
    for tag, response in sorted(responses.iteritems()):
      with api.step.nest('%s task results' % tag):
        _log_enumeration_errors(api, enumerations[tag])
        _log_task_results(api, response.task_results)
        if response.state.verdict not in _SUCCESSFUL_VERDICTS:
          step.logs['overall verdict'] = [
              TaskState.Verdict.Name(response.state.verdict)
          ]
          step.presentation.status = api.step.FAILURE
    if _contains_failed_verdict(responses):
      raise api.step.StepFailure('Some requests were unsuccessful')


def _contains_failed_verdict(responses):
  return any([
      r.state.verdict not in _SUCCESSFUL_VERDICTS
      for r in responses.itervalues()
  ])


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


#######################
# Keep this block in sync with recipe_modules/skylab/test_api.py
# TODO(chromium:1067440): refactor both to call the same code
def _marshal_responses(responses):
  responses_dict = json_format.MessageToDict(responses)
  return responses_dict.get("taggedResponses", {})


def _base64_compress_dict(some_dict):
  return json.dumps(some_dict).encode('zlib_codec').encode('base64_codec')


def _base64_compress_proto(proto):
  wire_format = proto.SerializeToString()
  return wire_format.encode('zlib_codec').encode('base64_codec')


# Keep this block in sync with recipe_modules/skylab/test_api.py
# TODO(chromium:1067440): refactor both to call the same code
#######################


def set_output_properties(api, responses):
  """Set the output properties that are part of the cros_test_platform API."""
  with api.step.nest('set output properties') as step:
    marshalled = _marshal_responses(responses)
    # Requests that specify a single request instead of a multi-request result
    # in a response tagged 'default'. Some clients that specify a single
    # request cannot handle compressed responses, see crbug.com/1086075.
    if 'default' in marshalled:
      step.properties['response'] = marshalled['default']

    step.properties['compressed_responses'] = _base64_compress_proto(responses)
    step.properties['compressed_json_responses'] = _base64_compress_dict(
        marshalled)


def _log_enumeration_errors(api, enumeration):
  if enumeration.error_summary:
    with api.step.nest('enumeration error') as step:
      step.logs['summary'] = [enumeration.error_summary]
      step.presentation.status = api.step.FAILURE


# The odd-looking string.replaced items below are listed as such to aid in code
# searchability. Users are most likely to search for these things after seeing
# them in Milo, and in Milo we display them with spaces rather than underscores.
_SUCCESSFUL_TASK_STATES = map(
    lambda s: s.replace(' ', '_'),
    [
        'passed',
        # Flakes are failed test runs that later succeed. e.g. if we run a test
        # and it fails, but then we retry it and the retry succeeds, we call the
        # first run a flake and the second run a pass.
        'flaked',
        'skipped',
    ],
)
_UNSUCCESSFUL_TASK_STATES = map(
    lambda s: s.replace(' ', '_'),
    [
        'failed all attempts',
        'bot parameters rejected',
        'timed out waiting for dut',
        'cancelled before run',
        'cancelled during run',
        'other',
    ],
)

_TaskResultsByState = collections.namedtuple(
    '_TaskResultsByState', _SUCCESSFUL_TASK_STATES + _UNSUCCESSFUL_TASK_STATES)


def _log_task_results(api, task_results):
  """Report task results for a request on the UI."""
  task_results_by_state = sort_task_results_by_state(task_results)

  for task_state, task_results in task_results_by_state._asdict().items():
    if task_results:
      with api.step.nest(task_state.replace('_', ' ')) as step:
        _emit_links(step, task_results)
        if task_state in _UNSUCCESSFUL_TASK_STATES:
          step.presentation.status = api.step.FAILURE


_PASSED_VERDICTS = [TaskState.VERDICT_PASSED, TaskState.VERDICT_PASSED_ON_RETRY]
_FAILED_VERDICTS = [TaskState.VERDICT_FAILED, TaskState.VERDICT_UNSPECIFIED]


def sort_task_results_by_state(task_results):
  task_results_by_state = _TaskResultsByState(
      passed=[], flaked=[], failed_all_attempts=[], skipped=[],
      bot_parameters_rejected=[], timed_out_waiting_for_dut=[],
      cancelled_before_run=[], cancelled_during_run=[], other=[])
  failed_at_least_once = []
  for tr in task_results:
    task_run_status = tr.state.life_cycle
    if task_run_status == TaskState.LIFE_CYCLE_REJECTED:
      task_results_by_state.bot_parameters_rejected.append(tr)
    elif task_run_status == TaskState.LIFE_CYCLE_CANCELLED:
      task_results_by_state.cancelled_before_run.append(tr)
    elif task_run_status == TaskState.LIFE_CYCLE_ABORTED:
      task_results_by_state.cancelled_during_run.append(tr)
    elif task_run_status == TaskState.LIFE_CYCLE_PENDING:
      task_results_by_state.timed_out_waiting_for_dut.append(tr)
    elif task_run_status == TaskState.LIFE_CYCLE_COMPLETED:
      task_verdict = tr.state.verdict
      if task_verdict in _PASSED_VERDICTS:
        task_results_by_state.passed.append(tr)
      elif task_verdict == TaskState.VERDICT_NO_VERDICT:
        task_results_by_state.skipped.append(tr)
      elif task_verdict in _FAILED_VERDICTS:
        # Don't assign state to failed tasks at this point, since we don't
        # know if they passed on retry or not.
        failed_at_least_once.append(tr)
    else:  # pragma: no cover
      task_results_by_state.other.append(tr)

  passed_set = set([x.name for x in task_results_by_state.passed])
  for tr in failed_at_least_once:
    if tr.name in passed_set:
      task_results_by_state.flaked.append(tr)
    else:
      task_results_by_state.failed_all_attempts.append(tr)

  return task_results_by_state


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
    if t.state.life_cycle not in [
        TaskState.LIFE_CYCLE_COMPLETED, TaskState.LIFE_CYCLE_RUNNING
    ]:
      # Log the task dimensions for any rejected tasks.
      if t.state.life_cycle == TaskState.LIFE_CYCLE_REJECTED and t.rejected_task_dimensions:
        step.logs['rejected dimensions for ' + t.name] = str(
            t.rejected_task_dimensions)

      if t.task_url:
        step.links['(task)  ' + t.name] = t.task_url
      else:
        step.links['(task)  ' + t.name + ' (no task link)'] = 'broken-link'
      continue
    suffix = ''
    if t.attempt > 0:
      suffix = ' attempt #%s' % str(t.attempt)
      if t.state.verdict in _PASSED_VERDICTS:
        suffix = suffix + ' passed on retry'
    step.links['(log)   ' + t.name + suffix] = t.log_url
    step.links['(task)  ' + t.name + suffix] = t.task_url


def _test_scheduling():
  return Request.Params.Scheduling(qs_account='foo-qs-account')


def _test_request(tag, scheduling=_test_scheduling()):
  return Request(
      params=Request.Params(
          hardware_attributes=Request.Params.HardwareAttributes(
              model='%s-model' % tag), metadata=Request.Params.Metadata(
                  test_metadata_url='%s-metadata-url' % tag,
                  debug_symbols_archive_url='%s-metadata-url' % tag),
          scheduling=scheduling),
      test_plan=Request.TestPlan(suite=[Request.Suite(name='%s-suite' % tag)]),
  )


def _test_config(tag):
  return Config(
      skylab_worker=Config.SkylabWorker(luci_project='%s luci project' % tag),
  )


def _test_single_enumeration(tag):
  # Note: using raw JSON here to avoid needing to import the chromite
  # protos.
  return '''
  {
    "tagged_responses": {
      "default": {
        "autotest_invocations": [{"test": {"name": "%s-test"}}]
      }
    }
  }''' % tag


def GenTests(api):
  # Missing request and requests should cause a recipe crash
  yield (api.test('no request or requests') +  #
         api.expect_exception("ValueError"))

  # Setting both request and requests should cause a recipe crash
  yield (api.test('both request and requests') +  #
         api.properties(
             CrosTestPlatformProperties(
                 request=Request(),
                 requests={'first': Request()},
             )) +  #
         api.expect_exception("ValueError"))

  # Traffic split with no traffic to skylab should cause recipe crash.
  yield (api.test('no traffic') +  #
         api.properties(
             CrosTestPlatformProperties(request=_test_request('default'))) +  #
         api.step_data(
             'traffic split.call binary.scheduler-traffic-split',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     SchedulerTrafficSplitResponses(tagged_responses={
                         'default': SchedulerTrafficSplitResponse()
                     })))) +  #
         api.expect_exception("ValueError"))

  # Request with a very long timeout should cause build failure.
  yield (api.test('timeout too long') +  #
         api.properties(
             CrosTestPlatformProperties(
                 request=Request(
                     params=Request.Params(
                         time=Request.Params.Time(
                             maximum_duration=duration_pb2.Duration(
                                 seconds=3600))),
                 ))))

  # Request with too large priority should cause build failure.
  yield (api.test('priority out of range') +  #
         api.properties(
             CrosTestPlatformProperties(
                 request=Request(
                     params=Request.Params(
                         scheduling=Request.Params.Scheduling(priority=300)),
                 ))))

  # Request setting both priority and qs_account should cause build failure.
  yield (api.test('both priority and qs_account set') +  #
         api.properties(
             CrosTestPlatformProperties(
                 request=Request(
                     params=Request.Params(
                         scheduling=Request.Params.Scheduling(
                             priority=100, qs_account='foo-qs-account')),
                 ))))

  # Config set the pubsub topic to push build ID.
  yield (
      api.test('Config has pubsub topic to publish CTP build ID') +  #
      api.buildbucket.build(build_pb2.Build(id=8874582904031090640)) +  #
      api.properties(
          CrosTestPlatformProperties(
              request=Request(), config=Config(
                  pubsub=Config.PubSub(project='foo-proj', topic='foo-topic'))))
      +  #
      api.step_data(
          'publish build ID.call `result_flow`.publish',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  result_flow_pb2.publish.PublishResponse(
                      state=result_flow_pb2.common.SUCCEEDED)))))

  # Recipe running outside Buildbucket should skip publishing build ID.
  yield (
      api.test('Recipe runs without Build ID') +  #
      api.buildbucket.build(build_pb2.Build(id=0)) +  #
      api.properties(
          CrosTestPlatformProperties(
              request=Request(), config=Config(
                  pubsub=Config.PubSub(project='foo-proj', topic='foo-topic'))))
  )

  # Config set the pubsub topic for test_runner.
  yield (
      api.test('Config has pubsub topic to publish test runner build ID') +  #
      api.buildbucket.build(build_pb2.Build(id=8874582904031090640)) +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'),
              config=Config(
                  test_runner=Config.TestRunner(
                      buildbucket=Config.Buildbucket(), pubsub=Config.PubSub(
                          project='foo-proj', topic='foo-topic')),
              ),
          ),
      ) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request(
                                      tag='foo',
                                      scheduling=Request.Params.Scheduling(
                                          unmanaged_pool='foo-pool',
                                          qs_account='foo-qs-account',
                                      ),
                                  ),
                              ),
                      })))) +  #
      api.step_data('enumerate tests.call binary.enumerate',
                    stdout=api.raw_io.output(_test_single_enumeration('foo'))))

  # An end-to-end run with traffic splitting to skylab.
  yield (
      api.test('end-to-end skylab execution with passed tasks') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_PASSED'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz',
                                          log_url='logs://bar/baz',
                                          name='foo-passed',
                                          state=TaskState(
                                              verdict="VERDICT_PASSED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                  ],
                              )
                      })))))

  yield (
      api.test('end-to-end skylab execution with passed and skipped tasks') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_PASSED'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz',
                                          log_url='logs://bar/baz',
                                          name='foo-passed',
                                          state=TaskState(
                                              verdict="VERDICT_PASSED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz1',
                                          log_url='logs://bar/baz1',
                                          name='foo-skipped',
                                          state=TaskState(
                                              verdict="VERDICT_NO_VERDICT",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                  ],
                              )
                      })))))

  yield (api.test('end-to-end skylab execution with empty response') +  #
         api.properties(
             CrosTestPlatformProperties(
                 request=_test_request('foo'), config=_test_config('foo'))) +  #
         api.step_data(
             'traffic split.call binary.scheduler-traffic-split',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     SchedulerTrafficSplitResponses(
                         tagged_responses={
                             'default':
                                 SchedulerTrafficSplitResponse(
                                     skylab_request=_test_request('foo'))
                         })))) +  #
         api.step_data(
             'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
                 _test_single_enumeration('foo'))) +  #
         api.step_data(
             'execute.call binary.skylab-execute', stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     ExecuteResponses(
                         tagged_responses={
                             'default':
                                 ExecuteResponse(
                                     state=TaskState(
                                         life_cycle='LIFE_CYCLE_ABORTED',
                                         verdict='VERDICT_FAILED'),
                                 )
                         })))))

  yield (
      api.test('end-to-end skylab execution with failed tasks') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_FAILED'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz',
                                          log_url='logs://bar/baz',
                                          name='foo-failed',
                                          state=TaskState(
                                              verdict="VERDICT_FAILED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz1',
                                          log_url='logs://bar/baz1',
                                          name='foo-failed',
                                          attempt=1,
                                          state=TaskState(
                                              verdict="VERDICT_FAILED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                  ],
                              )
                      })))))

  yield (
      api.test('end-to-end skylab execution with failed then passed tasks') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_PASSED_ON_RETRY'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz',
                                          log_url='logs://bar/baz',
                                          name='foo-retried',
                                          state=TaskState(
                                              verdict="VERDICT_FAILED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz1',
                                          log_url='logs://bar/baz1',
                                          name='foo-retried',
                                          attempt=1,
                                          state=TaskState(
                                              verdict="VERDICT_PASSED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                  ],
                              )
                      })))))

  yield (
      api.test('end-to-end skylab execution with retried tasks') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_PASSED_ON_RETRY'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz',
                                          log_url='logs://bar/baz',
                                          name='foo-retried',
                                          state=TaskState(
                                              verdict="VERDICT_FAILED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz1',
                                          log_url='logs://bar/baz1',
                                          name='foo-retried',
                                          attempt=1,
                                          state=TaskState(
                                              verdict="VERDICT_PASSED_ON_RETRY",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                  ],
                              )
                      })))))

  yield (
      api.test('end-to-end skylab execution with rejected tasks') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.skylab-execute',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_FAILED'),
                                  task_results=[
                                      # Include one result with task_url and
                                      # rejected_task_dimensions, and one without.
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz',
                                          log_url='logs://bar/baz', name='foo',
                                          state=TaskState(
                                              life_cycle="LIFE_CYCLE_REJECTED"),
                                          rejected_task_dimensions={
                                              'dim1': 'val1',
                                              'dim2': 'val2',
                                          }),
                                      ExecuteResponse.TaskResult(
                                          name='baz',
                                          state=TaskState(
                                              life_cycle="LIFE_CYCLE_REJECTED"),
                                      ),
                                  ],
                              )
                      })))))

  yield (
      api.test('end-to-end skylab execution with pending tasks') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_PENDING',
                                      verdict='VERDICT_FAILED'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url=None,
                                          log_url=None,
                                          name='foo-pending',
                                          state=TaskState(
                                              life_cycle="LIFE_CYCLE_PENDING"),
                                      ),
                                  ],
                              )
                      })))))

  yield (
      api.test('end-to-end skylab execution with cancelled tasks') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_CANCELLED',
                                      verdict='VERDICT_FAILED'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url=None,
                                          log_url=None,
                                          name='foo-cancelled',
                                          state=TaskState(
                                              life_cycle="LIFE_CYCLE_CANCELLED"
                                          ),
                                      ),
                                  ],
                              )
                      })))))
  yield (
      api.test('end-to-end skylab execution with aborted tasks') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_ABORTED',
                                      verdict='VERDICT_FAILED'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url=None,
                                          log_url=None,
                                          name='foo-aborted',
                                          state=TaskState(
                                              life_cycle="LIFE_CYCLE_ABORTED"),
                                      ),
                                  ],
                              )
                      })))))

  yield (api.test('too many traffic splitter responses') +  #
         api.properties(
             CrosTestPlatformProperties(
                 request=_test_request('foo'), config=_test_config('foo'))) +  #
         api.step_data(
             'traffic split.call binary.scheduler-traffic-split',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     SchedulerTrafficSplitResponses(
                         tagged_responses={
                             'default':
                                 SchedulerTrafficSplitResponse(
                                     skylab_request=_test_request('foo')),
                             'one_too_many':
                                 SchedulerTrafficSplitResponse(
                                     skylab_request=_test_request('foo'))
                         })))) +  #
         api.expect_exception("ValueError"))

  yield (
      api.test('enumeration error') +  #
      api.properties(
          CrosTestPlatformProperties(
              request=_test_request('foo'), config=_test_config('foo'))) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output('''
  {
    "tagged_responses": {
      "default": {
        "autotest_invocations": [{"test": {"name": "foo-test"}}],
        "error_summary": "some tests are missing"
      }
    }
  }''')) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'default':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_PASSED'))
                      })))))

  yield (
      api.test('skylab execution with two failed invocations') +  #
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first': _test_request('foo'),
                  'second': _test_request('foo'),
              }, config=_test_config('foo')),
      ) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'first':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo')),
                          'second':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output('''
  {
    "tagged_responses": {
      "first": {
        "autotest_invocations": [{"test": {"name": "foo-test"}}]
      },
      "second": {
        "autotest_invocations": [{"test": {"name": "baz-test"}}]
      }
    }
  }''')) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'first':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_FAILED'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz',
                                          log_url='logs://bar/baz',
                                          name='foo-failed',
                                          state=TaskState(
                                              verdict="VERDICT_FAILED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                  ],
                              ),
                          'second':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_FAILED'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz',
                                          log_url='logs://bar/baz',
                                          name='baz-failed',
                                          state=TaskState(
                                              verdict="VERDICT_FAILED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                  ],
                              ),
                      })))))

  yield (
      api.test('end-to-end multi-requests with skylab execution') +  #
      api.properties(
          CrosTestPlatformProperties(
              requests={'first': _test_request('foo')},
              config=_test_config('foo'),
          )) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'first':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output('''
  {
    "tagged_responses": {
      "first": {
        "autotest_invocations": [{"test": {"name": "foo-test"}}]
      }
    }
  }''')) +  #
      api.step_data(
          'execute.call binary.skylab-execute', stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ExecuteResponses(
                      tagged_responses={
                          'first':
                              ExecuteResponse(
                                  state=TaskState(
                                      life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_PASSED'),
                                  task_results=[
                                      ExecuteResponse.TaskResult(
                                          task_url='foo://bar/baz',
                                          log_url='logs://bar/baz',
                                          name='foo-passed',
                                          state=TaskState(
                                              verdict="VERDICT_PASSED",
                                              life_cycle='LIFE_CYCLE_COMPLETED'
                                          ),
                                      ),
                                  ],
                              )
                      })))) +  #
      api.post_check(lambda check, steps: check(
          len(GetBuildProperties(steps).get('compressed_responses', {})) > 0)))
