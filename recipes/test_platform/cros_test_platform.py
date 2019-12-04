# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Test Frontend.

TODO: Migrate to a recipes repo owned by the test team.
"""

from PB.recipes.chromeos.test_platform.cros_test_platform import \
  CrosTestPlatformProperties
from PB.recipes.chromeos.test_platform.cros_test_postprocess import \
  CrosTestPostprocessRequest
from PB.recipes.chromeos.test_platform.cros_test_postprocess import \
  TestResult as PostProcessTestResult
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
from PB.test_platform.steps.compute_backfill import \
    ComputeBackfillRequest, ComputeBackfillRequests
from PB.test_platform.steps.compute_backfill import \
    ComputeBackfillResponse, ComputeBackfillResponses
from PB.test_platform.request import Request
from PB.test_platform.taskstate import TaskState
from PB.test_platform.config.config import Config

import collections
import contextlib
import json

from google.protobuf import json_format

from recipe_engine.post_process import GetBuildProperties

DEPS = [
    'recipe_engine/buildbucket',
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
    split_req = SchedulerTrafficSplitRequests(
        tagged_requests={
            tag: SchedulerTrafficSplitRequest(
                request=r,
                config=config.scheduler_migration,
            ) for tag, r in requests.iteritems()
        })
    split_resp = api.cros_test_platform.scheduler_traffic_split(split_req)
    is_skylab, tagged_requests = _get_backend_requests(
        split_resp.tagged_responses)
    env_name = 'skylab' if is_skylab else 'autotest'
    step.presentation.step_summary_text = 'selected backend: ' + env_name
    return is_skylab, tagged_requests


def _get_backend_requests(split_responses):
  """Extract the backend request from traffic splitter response.

  Args:
    * split_resp: A test_platform.SchedulerTrafficSplitResponse object.

  Returns: bool, [test_platform.Request]
    * First item in the pair indicates whether this is a skylab request.
    * Second item in the pair is the list of extracted requests.
  """
  skylab_chosen = []
  tagged_requests = {}
  for tag, response in split_responses.iteritems():
    is_skylab, request = _get_backend_request(response)
    skylab_chosen.append(is_skylab)
    tagged_requests[tag] = request
  if len(set(skylab_chosen)) > 1:
    raise ValueError('Traffic splits contain both autotest and skylab'
                     ' across requests; this is not supported.')
  return skylab_chosen[0], tagged_requests


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
    _ensure_all_requests_enumerated(requests, enumerations)
    exec_reqs = ExecuteRequests(
        tagged_requests={
            t: ExecuteRequest(request_params=r.params,
                              enumeration=enumerations[t], config=config)
            for t, r in requests.iteritems()
        })
    if use_skylab:
      responses = api.cros_test_platform.skylab_execute(exec_reqs)
    else:
      responses = api.cros_test_platform.autotest_execute(exec_reqs)
    return responses.tagged_responses


def _ensure_all_requests_enumerated(requests, enumerations):
  missing = set(requests.keys()) - set(enumerations.keys())
  if missing:
    raise ValueError('No enumerations for requests tagged %s' % missing)


def compute_backfills(api, requests, enumerations, responses):
  """Compute backfill requests for this build.

  Args:
  requests: {tag: test_platform.Request} dict.
  enumerations: {tag: EnumerationResponse} dict.
  responses: {tag: ExecuteResponse} dict.
  """
  with api.step.nest('compute backfill'):
    reqs = ComputeBackfillRequests(
        tagged_requests={
            t: ComputeBackfillRequest(
                request=r,
                enumeration=enumerations[t],
                execution=responses.get(t, ExecuteResponse()),
            ) for t, r in requests.iteritems()
        })
    backfill = api.cros_test_platform.compute_backfill(reqs)
    return backfill.tagged_responses


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
    backfills = compute_backfills(api, requests, enumerations, responses)
    set_output_properties(api, responses, backfills)
    postprocess(api, requests, responses)
  summarize(api, responses)


def postprocess(api, requests, responses):
  with api.step.nest('postprocess') as step:
    for tag, response in responses.iteritems():
      request = requests[tag]
      if not request.params.metadata.debug_symbols_archive_url:
        continue # pragma: no cover

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
            debug_symbols_archive_url=
                request.params.metadata.debug_symbols_archive_url,
            test_results=test_results,
        )
        bb_request = api.buildbucket.schedule_request(
              bucket='testplatform',
              builder='cros_test_postprocess',
              properties=json_format.MessageToDict(pp_request),
        )
        api.buildbucket.schedule([bb_request])


def summarize(api, responses):
  # Failures in summarization are non-infra related.
  with api.step.nest('summarize') as step:
    for tag, response in responses.iteritems():
      with api.step.nest('%s task results' % tag):
        try:
          _log_task_results(api, response.task_results)
          if response.state.verdict not in [TaskState.VERDICT_PASSED]:
            raise api.step.StepFailure('%s task results' % tag)
        except api.step.StepFailure:
          pass
    if _some_response_contains_unsuccessful_results(responses):
      raise api.step.StepFailure('Some tests were unsuccessful')


def _some_response_contains_unsuccessful_results(responses):
  return any([
      _contains_unsuccessful_results(_classify_task_results(r.task_results))
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


def set_output_properties(api, responses, backfills):
  """Set the output properties that are part of the cros_test_platform API."""
  with api.step.nest('set output properties') as step:
    marshalled = {}
    for tag, response in responses.iteritems():
      marshalled[tag] = json_format.MessageToDict(response)
    step.properties['responses'] = marshalled
    if 'default' in marshalled:
      step.properties['response'] = marshalled['default']

    # TODO(crbug.com/1028420) Re-enable once a mitigation has landed on
    # buildbucket to bump up the limitation on output properties size.
    #
    # marshalled = {}
    # for tag, backfill in backfills.iteritems():
    #   marshalled[tag] = _marshal_proto_to_json(backfill.request)
    # step.properties['backfills'] = marshalled

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
    with _failing_substep(api, 'did not run due to DUT shortage') as step:
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
  failed_tasks = []
  for tr in task_results:
    # The order of these guard clauses is significant
    if (tr.state.verdict == TaskState.VERDICT_PASSED or
        tr.state.verdict == TaskState.VERDICT_PASSED_ON_RETRY):
      classified.passed.append(tr)
    elif tr.state.life_cycle == TaskState.LIFE_CYCLE_REJECTED:
      classified.rejected.append(tr)
    elif tr.state.verdict in (TaskState.VERDICT_FAILED,
                              TaskState.VERDICT_UNSPECIFIED):
      failed_tasks.append(tr)
    else:  # pragma: no cover
      classified.other.append(tr)

  passed_set = set([x.name for x in classified.passed])
  for tr in failed_tasks:
    if tr.name in passed_set:
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
    if t.state.life_cycle not in [
        TaskState.LIFE_CYCLE_COMPLETED, TaskState.LIFE_CYCLE_RUNNING
    ]:
      step.links['(task)  ' + t.name + ' did not run'] = t.task_url
      continue
    suffix = ''
    if t.attempt > 0:
      suffix = ' attempt #%s' % str(t.attempt)
      if (t.state.verdict == TaskState.VERDICT_PASSED_ON_RETRY or
          t.state.verdict == TaskState.VERDICT_PASSED):
        suffix = suffix + ' passed on retry'
    step.links['(log)   ' + t.name + suffix] = t.log_url
    step.links['(task)  ' + t.name + suffix] = t.task_url


def _test_request(tag):
  return Request(
      params=Request.Params(
          hardware_attributes=Request.Params.HardwareAttributes(
              model='%s-model' % tag),
          metadata=Request.Params.Metadata(
              test_metadata_url='%s-metadata-url' % tag,
              debug_symbols_archive_url='%s-metadata-url' % tag)
      ),
      test_plan=Request.TestPlan(suite=[Request.Suite(name='%s-suite' % tag)]),
  )


def _test_config(tag):
  return Config(
      skylab_worker=Config.SkylabWorker(luci_project='%s luci project' % tag),
      scheduler_migration=Config.SchedulerMigration(
          gitiles_host='%s gitiles host' % tag),
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
  yield (
    api.test('no request or requests') + #
    api.expect_exception("ValueError")
  )

  # Setting both request and requests should cause a recipe crash
  yield (api.test('both request and requests') +  #
         api.properties(
             CrosTestPlatformProperties(
                 request=Request(),
                 requests={'first': Request()},
             )) +  #
         api.expect_exception("ValueError"))

  # Traffic split with no traffic to either autotest or skylab
  # should cause recipe crash.
  yield (api.test('no traffic') +  #
         api.properties(CrosTestPlatformProperties(request=Request())) +  #
         api.step_data(
             'traffic split.call binary.scheduler-traffic-split',
             stdout=api.raw_io.output(
                 json_format.MessageToJson(
                     SchedulerTrafficSplitResponses(tagged_responses={
                         'default': SchedulerTrafficSplitResponse()
                     })))) +  #
         api.expect_exception("ValueError"))

  # Traffic split with traffic to both autotest and skylab
  # should cause recipe crash.
  yield (
      api.test('dual traffic') +  #
      api.properties(CrosTestPlatformProperties(request=Request())) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'default':
                              SchedulerTrafficSplitResponse(
                                  autotest_request=Request(
                                      test_plan=Request.TestPlan(
                                          suite=[Request.Suite(name="foo")]),),
                                  skylab_request=Request(
                                      test_plan=Request.TestPlan(
                                          suite=[Request.Suite(name="foo")]),),
                              )
                      })))) +  #
      api.expect_exception("ValueError"))

  # Traffic split with traffic to both autotest and skylab in different requests
  # should cause recipe crash.
  yield (
      api.test('dual traffic across requests') +  #
      api.properties(
          CrosTestPlatformProperties(requests={
              'first': Request(),
              'second': Request(),
          })) +  #
      api.step_data(
          'traffic split.call binary.scheduler-traffic-split',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  SchedulerTrafficSplitResponses(
                      tagged_responses={
                          'first':
                              SchedulerTrafficSplitResponse(
                                  autotest_request=Request(
                                      test_plan=Request.TestPlan(
                                          suite=[Request.Suite(
                                              name="foo")]),),),
                          'second':
                              SchedulerTrafficSplitResponse(
                                  skylab_request=Request(
                                      test_plan=Request.TestPlan(
                                          suite=[Request.Suite(name="foo")]),),)
                      })))) +  #
      api.expect_exception("ValueError"))

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
                                         verdict='VERDICT_FAILED'),)
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
                      })))) +  #
      api.step_data(
          'compute backfill.call binary.compute-backfill',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  ComputeBackfillResponses(tagged_responses={
                      'default': ComputeBackfillResponse(request=Request(),)
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
                                          name='foo-rejected',
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
      api.test('end-to-end with autotest execution') +  #
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
                                  autotest_request=_test_request('foo'))
                      })))) +  #
      api.step_data(
          'enumerate tests.call binary.enumerate', stdout=api.raw_io.output(
              _test_single_enumeration('foo'))) +  #
      api.step_data(
          'execute.call binary.autotest-execute', stdout=api.raw_io.output(
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
      api.test('skylab execution with two failed invocations') +  #
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first': _test_request('foo'),
                  'second': _test_request('foo'),
              }, config=_test_config('foo')),) +  #
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
    api.test('end-to-end multi-requests with skylab execution') + #
    api.properties(CrosTestPlatformProperties(
        requests={'first': _test_request('foo')},
        config=_test_config('foo'),
    )) + #
    api.step_data('traffic split.call binary.scheduler-traffic-split',
                  stdout=api.raw_io.output(
                    json_format.MessageToJson(SchedulerTrafficSplitResponses(
                        tagged_responses={
      'first': SchedulerTrafficSplitResponse(
          skylab_request=_test_request('foo'))
                    })))) + #
    api.step_data('enumerate tests.call binary.enumerate',
                  stdout=api.raw_io.output('''
  {
    "tagged_responses": {
      "first": {
        "autotest_invocations": [{"test": {"name": "foo-test"}}]
      }
    }
  }''')) + #
    api.step_data(
      'execute.call binary.skylab-execute',
      stdout=api.raw_io.output(
          json_format.MessageToJson(ExecuteResponses(tagged_responses={
            'first': ExecuteResponse(
                state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                verdict='VERDICT_PASSED'),
                task_results=[
                    ExecuteResponse.TaskResult(
                        task_url='foo://bar/baz',
                        log_url='logs://bar/baz',
                        name='foo-passed',
                        state=TaskState(verdict="VERDICT_PASSED",
                                        life_cycle='LIFE_CYCLE_COMPLETED'),
                    ),
                ],
            )
          })))) + #
    api.post_check(lambda check, steps: check(
        len(GetBuildProperties(steps).get('responses', {})) > 0))
  )
