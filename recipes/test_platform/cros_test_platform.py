# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Test Frontend."""

from PB.recipes.chromeos.test_platform.cros_test_platform import \
  CrosTestPlatformProperties
from PB.recipes.chromeos.test_platform.cros_test_postprocess import \
  CrosTestPostprocessRequest
from PB.recipes.chromeos.test_platform.cros_test_postprocess import \
  TestResult as PostProcessTestResult
from PB.recipe_modules.chromeos.service_version.service_version import \
  ServiceVersionProperties
from PB.test_platform import result_flow as result_flow_pb2
from PB.test_platform import service_version as service_version_pb
from PB.test_platform.steps.enumeration import \
  EnumerationRequest, EnumerationRequests
from PB.test_platform.steps.execution import ExecuteRequest, ExecuteRequests
from PB.test_platform.steps.execution import ExecuteResponse, ExecuteResponses
from PB.test_platform.request import Request
from PB.test_platform.taskstate import TaskState
from PB.test_platform.config.config import Config
from PB.test_platform.steps.execute.build import Build

import collections
import json
import re

from google.protobuf import duration_pb2
from google.protobuf import json_format

from recipe_engine.recipe_api import StepFailure
from recipe_engine import post_process
from recipe_engine.post_process import GetBuildProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/random',
    'recipe_engine/raw_io',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_tags',
    'cros_test_platform',
    'result_flow',
    'service_version',
]

# Each CIPD package instance of cros_test_platform that has been promoted to
# staging or prod is tagged with a timestamped release version.
CTP_RELEASE_VERSION_TAG = 'ctp_release_version'
PROPERTIES = CrosTestPlatformProperties

BUILD_ID_REGEX = re.compile(r'\/b(?P<build_id>[0-9]+)$')

# TODO(b/201608160): Remove upon completion of rollout.
CROS_GERRIT_RESULTS_EXP = 'chromeos.cros_test_platform.add_resultdb_settings'


def output_ctp_release_timestamp_tag(api):
  """Get the timestamped release tag of the cros_test_platform CIPD packages in use.
  """
  with api.step.nest('get ctp release version tag') as step:
    package_version = api.cros_test_platform.cipd_package_version()
    package_description = api.cipd.describe(
        'chromiumos/infra/cros_test_platform/${platform}', package_version)
    # CIPD allows multiple version tags.
    version_tags = [
        tag_data.tag
        for tag_data in package_description.tags
        if CTP_RELEASE_VERSION_TAG in tag_data.tag
    ]
    # Sort the list to get the most recent tag (version tags are in ISO
    # format, which sorts alphabetically).
    if version_tags:
      step.properties[CTP_RELEASE_VERSION_TAG] = sorted(version_tags)[-1]


def validated_requests(api, properties):
  """Get and validate requests from input properties.

  Returns: Struct containing requests.
  """
  requests = _get_requests_from_properties(api, properties)
  with api.step.nest('input validation'):
    with api.step.nest('service version'):
      api.service_version.validate_service_version_if_exists()

    validation_errors = []
    with api.step.nest('request'):
      validation_errors.append(_validate_timeouts(api, requests))
      validation_errors.append(_validate_scheduling_params(api, requests))
      validation_errors.append(_validate_software_dependencies(api, requests))
    if any(validation_errors):
      raise api.step.StepFailure('request validation failed')

  return requests


def _validate_software_dependencies(api, requests):
  """Validate the software dependencies are internally consistent.

  Returns: True if requests are valid, False otherwise.
  """
  validation_error = False
  with api.step.nest('software dependencies') as step:
    for t, r in requests.iteritems():
      errs = _invalid_software_dependencies(r.params.software_dependencies)
      if errs:
        step.presentation.logs[t] = [
            'Errors in software_dependencies: %s' % ', '.join(errs)
        ]
        validation_error = True
  return validation_error


def _invalid_software_dependencies(deps):
  """Return a list of validation errors for provided software_dependencies."""
  errs = []
  seen = set()
  for dep_oneof in deps:
    dep = dep_oneof.WhichOneof('dep')
    if dep in seen:
      errs.append('has duplicate %s' % dep)
    seen.add(dep)
  # Only report duplicates once for each kind.
  return list(set(errs))


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
      error = _get_scheduling_error(r)
      if error:
        validation_error = True
        step.presentation.logs[t] = [error]
        step.presentation.status = api.step.FAILURE
  return validation_error


_MANAGED_POOL_ALLOW_LIST = (
    Request.Params.Scheduling.MANAGED_POOL_UNSPECIFIED,
    Request.Params.Scheduling.MANAGED_POOL_QUOTA,
    Request.Params.Scheduling.MANAGED_POOL_CTS,
)


def _get_scheduling_error(request):
  managed_pool = request.params.scheduling.managed_pool
  if managed_pool not in _MANAGED_POOL_ALLOW_LIST:
    return ('Pool %s not supported. See go/managed-pools-deprecation' %
            Request.Params.Scheduling.ManagedPool.Name(managed_pool))

  qs_account = request.params.scheduling.qs_account
  priority = request.params.scheduling.priority
  if not priority and not qs_account:
    return 'Exactly one of priority and qs_account must be set. Found none.'
  if priority:
    if qs_account:
      return ('priority and qs_account should not both be set. ' +
              'Got priority: %d and qs_account: %s' % (priority, qs_account))
    if priority < 50 or priority > 255:
      return 'priority %d is out of valid range [50, 255]' % priority


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
      _log_enumeration_errors(api, response)
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


def publish_to_result_flow(api, config, should_poll_for_completion=False):
  """Publish build info to result_flow PubSub

  Args:
  * config: test_platform.Config instance.
  * should_poll_for_completion (bool): If true, the consumers should not ACK
                                       the message until the build is complete.
  """
  with api.step.nest('publish build ID') as step:
    if not api.buildbucket.build.id:
      step.presentation.step_summary_text = 'Skipped: Build ID not set'
      return
    if not config.pubsub.topic:
      step.presentation.step_summary_text = 'Skipped: PubSub topic not set'
      return
    if not config.pubsub.project:
      step.presentation.step_summary_text = 'Skipped: PubSub project not set'
      return
    api.result_flow.publish(
        project_id=config.pubsub.project, topic_id=config.pubsub.topic,
        build_type='ctp', should_poll_for_completion=should_poll_for_completion)


def execute(api, requests):
  """Execute request in the correct backend.

  Args:
    requests: ExecutionRequests payload.
  """
  with api.step.nest('execute'):
    return api.cros_test_platform.execute_luciexe(requests)


def _execute_requests(api, requests, enumerations, config):
  """Create the request payload for execution.
  Args:
    requests: {tag: test_platform.Request} dict.
    enumerations: {tag: EnumerationResponse} dict.
    config: test_platform.Config instance.

  Returns:
    ExecutionRequests payload.
  """
  _ensure_all_requests_enumerated(requests, enumerations)
  return ExecuteRequests(
      tagged_requests={
          t: ExecuteRequest(request_params=r.params,
                            enumeration=enumerations[t], config=config)
          for t, r in requests.iteritems()
      },
      build=Build(id=api.buildbucket.build.id,
                  create_time=api.buildbucket.build.create_time),
  )


def _ensure_all_requests_enumerated(requests, enumerations):
  missing = set(requests.keys()) - set(enumerations.keys())
  if missing:
    raise StepFailure('No enumerations for requests tagged %s' % missing)


def RunSteps(api, properties):
  # Log which cros_test_platform release version the tests will run on.
  output_ctp_release_timestamp_tag(api)
  link_to_parent(api)
  # Push Build ID to Pubsub to notify the subscribers that a new CTP
  # build is about to run.
  publish_to_result_flow(api, properties.config)
  requests = validated_requests(api, properties)
  with api.context(infra_steps=True):
    enumerations = enumerate_tests(api, requests)
    responses = execute(
        api, _execute_requests(api, requests, enumerations, properties.config))
    tagged_responses = responses.tagged_responses
    set_output_properties(api, responses)
    # Push the Build ID to notify the subscribers that test plan execution
    # is completed.
    publish_to_result_flow(api, properties.config,
                           should_poll_for_completion=True)
    postprocess(api, requests, tagged_responses)
  summarize(api, enumerations, tagged_responses)


def link_to_parent(api):
  build = api.buildbucket.build
  parent = [x.value for x in build.tags if x.key == 'parent_buildbucket_id']
  if parent:
    with api.step.nest('link to parent') as presentation:
      presentation.links['parent link'] = api.buildbucket.build_url(
          build_id=parent[0])


def postprocess(api, requests, responses):
  with api.step.nest('postprocess'):
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

      with api.step.nest(tag):
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

_REQUEST_SUCCESS = 'Succeeded'
_REQUEST_FAILURE = 'Failed with complete results'
_REQUEST_INCOMPLETE_FAILURE = 'Failed with incomplete results'
_REQUEST_REJECTED_PARAMETERS = 'Bot parameters rejected'
_REQUEST_STATES = [
    _REQUEST_SUCCESS,
    _REQUEST_FAILURE,
    _REQUEST_INCOMPLETE_FAILURE,
    _REQUEST_REJECTED_PARAMETERS,
]


def _is_incomplete_result(task_result):
  """Determine whether the task failed without completing the test execution."""
  if task_result.state.life_cycle != TaskState.LIFE_CYCLE_COMPLETED:
    return True

  # There are cases in which the task's lifecycle is complete, but no test cases
  # ran due to an autoserv error (e.g. http://go/bbid/8825690244767207153).
  if not task_result.test_cases:
    return True

  # There are cases in which the task failed to launch Tast, but the lifecycle
  # is marked as complete (e.g. http://go/bbid/8825690244767207153).
  if (len(task_result.test_cases) == 1 and
      task_result.test_cases[0].name == 'tast'):
    return True

  return False


def _classify_request_failure(consolidated_results):
  """Determine the state of the failed request based on the task results.

  Args:
    consolidated_results (list[ExecuteResponse.ConsolidatedResult]): The grouped
        results for each enumeration.
  Returns:
    The state for the given request based on the results.
  """

  for result in consolidated_results:
    if all(t.state.life_cycle == TaskState.LIFE_CYCLE_REJECTED
           for t in result.attempts):
      return _REQUEST_REJECTED_PARAMETERS
    elif all(_is_incomplete_result(t) for t in result.attempts):
      # If any enumeration only produced incomplete results, the entire request
      # will be classified as incomplete, so we don't have to continue looking
      # at the other results.
      return _REQUEST_INCOMPLETE_FAILURE

  # If no failures with incomplete results or rejected parameters are detected,
  # then we can say the request failed with complete results.
  return _REQUEST_FAILURE


def summarize(api, enumerations, responses):
  # Failures in summarization are non-infra related.
  failures = 0
  invocations = []

  request_classifications = collections.OrderedDict()
  for state in _REQUEST_STATES:
    request_classifications[state] = 0

  with api.step.nest('summarize') as step:
    for tag, response in sorted(responses.iteritems()):
      with api.step.nest('%s task results' % tag):
        _log_enumeration_errors(api, enumerations[tag])
        _log_task_results(api, response.task_results)
        # TODO(b/201608160): Remove conditional upon experiment completion.
        if api.cros_test_platform.add_to_resultdb:
          invocations.extend(_get_rdb_invocations(response.task_results))
        if response.state.verdict in _SUCCESSFUL_VERDICTS:
          request_classifications[_REQUEST_SUCCESS] += 1
        else:
          failures += 1
          step.logs['overall verdict'] = [
              TaskState.Verdict.Name(response.state.verdict)
          ]
          classification = _classify_request_failure(
              response.consolidated_results)
          request_classifications[classification] += 1
          step.presentation.status = api.step.FAILURE

    # TODO(b/201608160): In order for test results to appear on Gerrit they must
    # be inherited by the cros_test_platform builder.
    # Remove check for experiment when go/cros-gerrit-results rollout concludes.
    if (invocations and api.resultdb.enabled and
        CROS_GERRIT_RESULTS_EXP in api.cros_infra_config.experiments):
      api.resultdb.include_invocations(api.resultdb.invocation_ids(invocations))

    if failures:
      summary_lines = [
          '%s out of %s requests were unsuccessful' % (failures, len(responses))
      ]
      for state, val in request_classifications.items():
        if val > 0:
          summary_lines.append('- %s: %s request%s' %
                               (state, val, '' if val == 1 else 's'))
      summary_markdown = '\n\n'.join(summary_lines)
      raise api.step.StepFailure(summary_markdown)

    if not responses:
      raise api.step.StepFailure('No requests ran')

def _get_requests_from_properties(api, properties):
  if properties.HasField('request'):
    raise api.step.StepFailure(
        'This request was made using an outdated version of the skylab tool. '
        'Please `skylab update` and try again. If you\'re stuck on this, '
        'please see http://go/skylab-cli')
  if not properties.requests:
    raise api.step.StepFailure(
        'Must set "requests" in input properties (found %s)' %
        properties.requests)
  return properties.requests


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


def _log_enumeration_errors(api, enum):
  if enum.error_summary:
    with api.step.nest('enumeration error') as step:
      step.logs['summary'] = [enum.error_summary]
      step.presentation.status = api.step.FAILURE


# The odd-looking string.replaced items below are listed as such to aid in code
# searchability. Users are most likely to search for these things after seeing
# them in Milo, and in Milo we display them with spaces rather than underscores.
_SUCCESSFUL_TASK_STATES = [
    s.replace(' ', '_') for s in [
        'passed',
        # Flakes are failed test runs that later succeed. e.g. if we run a test
        # and it fails, but then we retry it and the retry succeeds, we call the
        # first run a flake and the second run a pass.
        'flaked',
        'skipped',
    ]
]
_UNSUCCESSFUL_TASK_STATES = [
    s.replace(' ', '_') for s in [
        'failed all attempts',
        'bot parameters rejected',
        'timed out waiting for dut',
        'cancelled before run',
        'cancelled during run',
        'other',
    ]
]

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


def _get_rdb_invocations(task_results):
  """Get the test_runner invocation names from the task results."""
  invs = []
  for t in task_results:
    res = re.search(BUILD_ID_REGEX, t.task_url)
    if res.group('build_id'):
      inv = 'invocations/build-%s' % res.group('build_id')
      invs.append(inv)
  return invs


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
  for i, t in enumerate(task_results, 1):
    if t.state.life_cycle not in [
        TaskState.LIFE_CYCLE_COMPLETED, TaskState.LIFE_CYCLE_RUNNING
    ]:
      # Log the task dimensions for any rejected tasks.
      if t.state.life_cycle == TaskState.LIFE_CYCLE_REJECTED and t.rejected_dimensions:
        step.logs['rejected dimensions for ' + t.name] = str(
            t.rejected_dimensions)

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
    step.links[str(i) + '. (log)   ' + t.name + suffix] = t.log_url
    step.links[str(i) + '. (task)  ' + t.name + suffix] = t.task_url


def _test_scheduling():
  return Request.Params.Scheduling(qs_account='foo-qs-account')


def _default_software_dependencies():
  return [
      Request.Params.SoftwareDependency(
          chromeos_build="single-build",
      ),
      Request.Params.SoftwareDependency(
          ro_firmware_build="single-ro-firmware",
      ),
      Request.Params.SoftwareDependency(
          rw_firmware_build="single-rw-firmware",
      ),
  ]


def _test_request(tag, scheduling=_test_scheduling()):
  return Request(
      params=Request.Params(
          hardware_attributes=Request.Params.HardwareAttributes(
              model='%s-model' % tag),
          metadata=Request.Params.Metadata(
              test_metadata_url='%s-metadata-url' % tag,
              debug_symbols_archive_url='%s-metadata-url' % tag),
          scheduling=scheduling,
          software_dependencies=_default_software_dependencies(),
      ),
      test_plan=Request.TestPlan(suite=[Request.Suite(name='%s-suite' % tag)]),
  )


def _test_config(tag):
  return Config(
      skylab_worker=Config.SkylabWorker(luci_project='%s luci project' % tag),
  )


def _succeeded_request_execute_response():
  tr = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='foo-passed',
      state=TaskState(verdict="VERDICT_PASSED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  return ExecuteResponse(
      state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                      verdict='VERDICT_PASSED'), task_results=[
                          tr,
                      ], consolidated_results=[
                          ExecuteResponse.ConsolidatedResult(attempts=[
                              tr,
                          ]),
                      ])


def _parameters_rejected_execute_response():
  tr = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='foo-rejected',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_REJECTED'),
  )
  return ExecuteResponse(
      state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                      verdict='VERDICT_FAILED'), task_results=[
                          tr,
                      ], consolidated_results=[
                          ExecuteResponse.ConsolidatedResult(attempts=[
                              tr,
                          ]),
                      ])


def _incomplete_failure_execute_response():
  complete_tr_1 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  complete_tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )

  incomplete_tr_1 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_ABORTED'),
  )
  incomplete_tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_PENDING'),
  )
  return ExecuteResponse(
      state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                      verdict='VERDICT_FAILED'), task_results=[
                          complete_tr_1,
                          complete_tr_2,
                          incomplete_tr_1,
                          incomplete_tr_2,
                      ], consolidated_results=[
                          ExecuteResponse.ConsolidatedResult(
                              attempts=[complete_tr_1, complete_tr_2]),
                          ExecuteResponse.ConsolidatedResult(
                              attempts=[incomplete_tr_1, incomplete_tr_2])
                      ])


def _failure_with_no_test_cases():
  tr_1 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )

  return ExecuteResponse(
      state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                      verdict='VERDICT_FAILED'), task_results=[
                          tr_1,
                          tr_2,
                      ],
      consolidated_results=[
          ExecuteResponse.ConsolidatedResult(attempts=[tr_1, tr_2]),
      ])


def _tast_incomplete_failure_execute_response():
  tr_1 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='bar-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_ABORTED'),
  )
  tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='bar-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
      test_cases=[
          ExecuteResponse.TaskResult.TestCaseResult(
              name='tast', verdict=TaskState.VERDICT_FAILED)
      ],
  )

  return ExecuteResponse(
      state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                      verdict='VERDICT_FAILED'), task_results=[
                          tr_1,
                          tr_2,
                      ],
      consolidated_results=[
          ExecuteResponse.ConsolidatedResult(attempts=[tr_1, tr_2]),
      ])


def _complete_failure_execute_response():
  tr_1 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='bar-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_ABORTED'),
  )
  tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='bar-fail',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
      test_cases=[
          ExecuteResponse.TaskResult.TestCaseResult(
              name='failed-test-case', verdict=TaskState.VERDICT_FAILED)
      ],
  )

  return ExecuteResponse(
      state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                      verdict='VERDICT_FAILED'), task_results=[
                          tr_1,
                          tr_2,
                      ],
      consolidated_results=[
          ExecuteResponse.ConsolidatedResult(attempts=[tr_1, tr_2]),
      ])


def _generic_enumerate_response(api):
  return api.cros_test_platform.set_enumerate_response_json(
      'enumerate tests',
      '''
{
  "tagged_responses": {
    "default": {
      "autotest_invocations": [{"test": {"name": "foo-test"}}]
    }
  }
}''',
  )


def _empty_enumerate_response(api):
  return api.cros_test_platform.set_enumerate_response_json(
      'enumerate tests',
      '{ "tagged_responses": {} }',
  )


def _generic_passing_execute_response(api):
  task_results = [
      ExecuteResponse.TaskResult(
          task_url='foo://bar/baz/b100',
          log_url='logs://bar/baz',
          name='foo-passed',
          state=TaskState(verdict="VERDICT_PASSED",
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
  ]
  return api.cros_test_platform.set_execute_luciexe_response(
      'execute',
      ExecuteResponses(
          tagged_responses={
              'default':
                  ExecuteResponse(
                      state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                      verdict='VERDICT_PASSED'),
                      task_results=task_results, consolidated_results=[
                          ExecuteResponse.ConsolidatedResult(
                              attempts=task_results)
                      ])
          }))


def GenTests(api):

  def _set_build(bid=None, tags=None, experiments=None):
    # tags is a dict, convert that into [StringPair].
    bb_tags = api.cros_tags.tags(**tags) if tags else []
    return api.buildbucket.ci_build(build_id=bid, tags=bb_tags,
                                    experiments=experiments, project='chromeos',
                                    bucket='testplatform',
                                    builder='cros_test_platform')


  # Missing request and requests should cause a recipe crash
  yield api.test('no requests')

  # Setting request should cause a recipe crash
  yield api.test(
      'has deprecated request',
      api.properties(
          CrosTestPlatformProperties(
              request=Request(),
              requests={'first': Request()},
          )))

  # Request with a very long timeout should cause build failure.
  yield api.test(
      'timeout too long',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first':
                      Request(
                          params=Request.Params(
                              scheduling=Request.Params.Scheduling(
                                  priority=100), time=Request.Params.Time(
                                      maximum_duration=duration_pb2.Duration(
                                          seconds=3600))),
                      )
              })))

  yield api.test(
      'neither priority and qs_account set',
      api.properties(CrosTestPlatformProperties(requests={'first': Request()})))

  # Request with too large priority should cause build failure.
  yield api.test(
      'priority out of range',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first':
                      Request(
                          params=Request.Params(
                              scheduling=Request.Params.Scheduling(
                                  priority=300)),
                      )
              })))

  # Request setting both priority and qs_account should cause build failure.
  yield api.test(
      'both priority and qs_account set',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first':
                      Request(
                          params=Request.Params(
                              scheduling=Request.Params.Scheduling(
                                  priority=100, qs_account='foo-qs-account')),
                      )
              })))

  yield api.test(
      'deprecated managed pool',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first':
                      Request(
                          params=Request.Params(
                              scheduling=Request.Params.Scheduling(
                                  priority=120,
                                  managed_pool='MANAGED_POOL_BVT',
                              )))
              })))

  yield api.test(
      'skylab-tool-launched build with invalid service version',
      api.properties(
          CrosTestPlatformProperties(requests={'first': Request()}), **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version_pb.ServiceVersion(skylab_tool=2)),
          }))

  yield api.test(
      'skylab-tool-launched build with valid service version',
      api.properties(
          CrosTestPlatformProperties(requests={'first': Request()}), **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version_pb.ServiceVersion(skylab_tool=3)),
          }))

  yield api.test(
      'Duplicate software dependencies',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first':
                      Request(
                          params=Request.Params(
                              scheduling=Request.Params.Scheduling(
                                  qs_account='foo-qs-account'),
                              software_dependencies=[
                                  Request.Params.SoftwareDependency(
                                      chromeos_build="duplicate-build",
                                  ),
                                  Request.Params.SoftwareDependency(
                                      chromeos_build="duplicate-build",
                                  ),
                                  Request.Params.SoftwareDependency(
                                      ro_firmware_build="single-ro-firmware",
                                  ),
                                  Request.Params.SoftwareDependency(
                                      rw_firmware_build="duplicate-rw-firmware",
                                  ),
                                  Request.Params.SoftwareDependency(
                                      rw_firmware_build="duplicate-rw-firmware-diff-value",
                                  ),
                              ],
                          ),
                      )
              },
          ),
      ))

  # Config set the result flow pubsub project and topic should push build ID.
  yield api.test(
      'Config has pubsub topic to publish CTP build ID',
      _set_build(bid=42, tags={'parent_buildbucket_id': '1234'}),
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _test_request('default')},
              config=Config(
                  pubsub=Config.PubSub(project='foo-proj', topic='foo-topic')),
          )),
      api.step_data(
          'publish build ID.call `result_flow`.publish',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  result_flow_pb2.publish.PublishResponse(
                      state=result_flow_pb2.common.SUCCEEDED)))),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  # Recipe running outside Buildbucket should skip publishing build ID.
  yield api.test(
      'Recipe runs without Build ID', _set_build(bid=0),
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _test_request('default')},
              config=Config(
                  pubsub=Config.PubSub(project='foo-proj', topic='foo-topic')),
          )), _generic_enumerate_response(api),
      _generic_passing_execute_response(api))

  # Config missing result flow topic name should skip publishing build ID.
  yield api.test(
      'Recipe runs without result flow pubsub topic',
      _set_build(bid=8874582904031090640),
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _test_request('default')},
              config=Config(pubsub=Config.PubSub(project='foo-proj')))),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  # Config missing result flow project name should skip publishing build ID.
  yield api.test(
      'Recipe runs without result flow pubsub project',
      _set_build(bid=8874582904031090640),
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _test_request('default')},
              config=Config(pubsub=Config.PubSub(topic='foo-topic')))),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  task_result_1 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='foo-passed',
      state=TaskState(verdict="VERDICT_PASSED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )

  task_result_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b101',
      log_url='logs://bar/baz1',
      name='foo-skipped',
      state=TaskState(verdict="VERDICT_NO_VERDICT",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  # TODO(b/201608160): Remove upon experiment completion.
  yield api.test(
      'end-to-end execution with resultdb experiment enabled',
      _set_build(
          bid=8874582904031090640,
          experiments=['chromeos.cros_test_platform.add_resultdb_settings']),
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api), _generic_passing_execute_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_PASSED'),
                          task_results=[
                              task_result_1,
                              task_result_2,
                          ], consolidated_results=[
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=[task_result_1]),
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=[task_result_2])
                          ])
              }),
      ))

  # An end-to-end run with ctp release version tagging.
  yield api.test(
      'end-to-end skylab execution with ctp release version tagging',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_PASSED'),
                          task_results=[],
                          consolidated_results=[],
                      )
              })),
      api.override_step_data(
          'get ctp release version tag.cipd describe chromiumos/infra/cros_test_platform/${platform}',
          api.cipd.example_describe(
              'chromiumos/infra/cros_test_platform/${platform}',
              version='latest', test_data_tags=[
                  'ctp_release_version:ctp_2020-08-31T15:50:00.807944',
                  'ctp_release_version:ctp_2020-08-31T16:53:00.807944',
                  'ctp_release_version:ctp_2020-08-31T16:42:54.412755',
                  'random-key:random-value',
              ])))

  # An end-to-end run without ctp release version tagging.
  yield api.test(
      'end-to-end skylab execution with no ctp release version found',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_PASSED'),
                          task_results=[],
                          consolidated_results=[],
                      )
              })),
      api.override_step_data(
          'get ctp release version tag.cipd describe chromiumos/infra/cros_test_platform/${platform}',
          api.cipd.example_describe(
              'chromiumos/infra/cros_test_platform/${platform}',
              version='latest', test_data_tags=['random-key:random-value'])))

  yield api.test(
      'end-to-end execution with passed tasks',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  passed_task_result = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='foo-passed',
      state=TaskState(verdict="VERDICT_PASSED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  skipped_task_result = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b101',
      log_url='logs://bar/baz1',
      name='foo-skipped',
      state=TaskState(verdict="VERDICT_NO_VERDICT",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  yield api.test(
      'end-to-end execution with passed and skipped tasks',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_PASSED'),
                          task_results=[
                              passed_task_result,
                              skipped_task_result,
                          ],
                          consolidated_results=[
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=[passed_task_result]),
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=[skipped_task_result]),
                          ],
                      )
              }),
      ))

  yield api.test(
      'end-to-end execution with empty response',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(tagged_responses={}),
      ))

  failed_task_results = [
      ExecuteResponse.TaskResult(
          task_url='foo://bar/baz/b100',
          log_url='logs://bar/baz',
          name='foo-failed',
          state=TaskState(verdict="VERDICT_FAILED",
                          life_cycle='LIFE_CYCLE_COMPLETED'),
          test_cases=[
              ExecuteResponse.TaskResult.TestCaseResult(
                  name='failed-test-case', verdict=TaskState.VERDICT_FAILED)
          ],
      ),
      ExecuteResponse.TaskResult(
          task_url='foo://bar/baz/b101',
          log_url='logs://bar/baz1',
          name='foo-failed',
          attempt=1,
          state=TaskState(verdict="VERDICT_FAILED",
                          life_cycle='LIFE_CYCLE_COMPLETED'),
          test_cases=[
              ExecuteResponse.TaskResult.TestCaseResult(
                  name='failed-test-case', verdict=TaskState.VERDICT_FAILED)
          ],
      ),
  ]
  yield api.test(
      'end-to-end execution with failed tasks',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_FAILED'),
                          task_results=failed_task_results,
                          consolidated_results=[
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=failed_task_results)
                          ])
              }),
      ))

  retried_task_results = [
      ExecuteResponse.TaskResult(
          task_url='foo://bar/baz/b100',
          log_url='logs://bar/baz',
          name='foo-retried',
          state=TaskState(verdict="VERDICT_FAILED",
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='foo://bar/baz/b101',
          log_url='logs://bar/baz1',
          name='foo-retried',
          attempt=1,
          state=TaskState(verdict="VERDICT_PASSED",
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
  ]
  yield api.test(
      'end-to-end execution with failed then passed tasks',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_PASSED_ON_RETRY'),
                          task_results=retried_task_results,
                          consolidated_results=[
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=retried_task_results)
                          ])
              }),
      ))

  task_result_baz = ExecuteResponse.TaskResult(
      name='baz',
      state=TaskState(life_cycle="LIFE_CYCLE_REJECTED"),
  )
  task_result_foo = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100', log_url='logs://bar/baz', name='foo',
      state=TaskState(life_cycle="LIFE_CYCLE_REJECTED"), rejected_dimensions=[
          ExecuteResponse.TaskResult.RejectedTaskDimension(
              key='dim1', value='val1'),
          ExecuteResponse.TaskResult.RejectedTaskDimension(
              key='dim2', value='val2'),
      ])
  yield api.test(
      'end-to-end execution with rejected tasks',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_FAILED'),
                          task_results=[
                              # Include one result with task_url and
                              # rejected_task_dimensions, and one without.
                              task_result_foo,
                              task_result_baz,
                          ],
                          consolidated_results=[
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=[task_result_foo]),
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=[task_result_baz]),
                          ],
                      )
              }),
      ))

  pending_task_result = ExecuteResponse.TaskResult(
      task_url=None,
      log_url=None,
      name='foo-pending',
      state=TaskState(life_cycle="LIFE_CYCLE_PENDING"),
  )
  yield api.test(
      'end-to-end execution with pending tasks',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_PENDING',
                                          verdict='VERDICT_FAILED'),
                          task_results=[
                              pending_task_result,
                          ],
                          consolidated_results=[
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=[pending_task_result]),
                          ],
                      )
              }),
      ))

  task_results = [
      ExecuteResponse.TaskResult(
          task_url=None,
          log_url=None,
          name='foo-cancelled',
          state=TaskState(life_cycle="LIFE_CYCLE_CANCELLED"),
      ),
  ]
  yield api.test(
      'end-to-end execution with cancelled tasks',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_CANCELLED',
                                          verdict='VERDICT_FAILED'),
                          task_results=task_results,
                          consolidated_results=[
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=task_results),
                          ],
                      ),
              }),
      ))

  aborted_task_result = ExecuteResponse.TaskResult(
      task_url=None,
      log_url=None,
      name='foo-aborted',
      state=TaskState(life_cycle="LIFE_CYCLE_ABORTED"),
  )
  yield api.test(
      'end-to-end execution with aborted tasks',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_ABORTED',
                                          verdict='VERDICT_FAILED'),
                          task_results=[aborted_task_result
                                       ], consolidated_results=[
                                           ExecuteResponse.ConsolidatedResult(
                                               attempts=task_results)
                                       ])
              }),
      ))

  yield api.test(
      'empty enumeration',
      api.properties(
          CrosTestPlatformProperties(requests={'first': _test_request('foo')},
                                     config=_test_config('foo'))),
      _empty_enumerate_response(api),
      api.post_check(post_process.StatusFailure))

  yield api.test(
      'enumeration error',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      api.cros_test_platform.set_enumerate_response_json(
          'enumerate tests',
          '''
  {
    "tagged_responses": {
      "default": {
        "autotest_invocations": [{"test": {"name": "foo-test"}}],
        "error_summary": "some tests are missing"
      }
    }
  }''',
      ),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_PASSED'))
              }),
      ))

  task_result_foo = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='foo-failed',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  task_result_baz = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-failed',
      state=TaskState(verdict="VERDICT_FAILED",
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  yield api.test(
      'execution with two failed invocations',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first': _test_request('foo'),
                  'second': _test_request('foo'),
              }, config=_test_config('foo')),
      ),
      api.cros_test_platform.set_enumerate_response_json(
          'enumerate tests',
          '''
  {
    "tagged_responses": {
      "first": {
        "autotest_invocations": [{"test": {"name": "foo-test"}}]
      },
      "second": {
        "autotest_invocations": [{"test": {"name": "baz-test"}}]
      }
    }
  }''',
      ),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'first':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_FAILED'),
                          task_results=[
                              task_result_foo,
                          ]),
                  'second':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_FAILED'),
                          task_results=[
                              task_result_baz,
                          ],
                      ),
              }),
      ))

  yield api.test(
      'end-to-end multi-requests',
      api.properties(
          CrosTestPlatformProperties(
              requests={'first': _test_request('foo')},
              config=_test_config('foo'),
          )),
      api.cros_test_platform.set_enumerate_response_json(
          'enumerate tests',
          '''
  {
    "tagged_responses": {
      "first": {
        "autotest_invocations": [{"test": {"name": "foo-test"}}]
      }
    }
  }''',
      ),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'first': _succeeded_request_execute_response(),
                  'second': _complete_failure_execute_response(),
                  'third': _incomplete_failure_execute_response(),
                  'fourth': _parameters_rejected_execute_response(),
                  'fifth': _failure_with_no_test_cases(),
                  'sixth': _tast_incomplete_failure_execute_response(),
              }),
      ),
      api.post_check(lambda check, steps: check(
          len(GetBuildProperties(steps).get('compressed_responses', {})) > 0)))
