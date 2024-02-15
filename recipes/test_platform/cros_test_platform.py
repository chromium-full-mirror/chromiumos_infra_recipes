# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the ChromeOS Test Frontend."""

import collections
import csv
import datetime
import json
import math
import re
from io import StringIO

from google.protobuf import duration_pb2
from google.protobuf import json_format

from PB.chromite.api import test_metadata
from PB.chromiumos.build.api.container_metadata import ContainerMetadata
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.test.api import cros_tool_runner_cli as ctr
from PB.chromiumos.test.api import test_case as ctr_test_case
from PB.chromiumos.test.api import test_suite as ctr_test_suite
from PB.chromiumos.test.api import pre_test_service as pre_request
from PB.chromiumos.test.api import cros_test_finder_cli as ctf

from PB.go.chromium.org.luci.resultdb.proto.v1 import (
    invocation as invocation_pb2,)
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner import (
    CrosToolRunnerProperties,)
from PB.recipe_modules.chromeos.service_version.service_version import (
    ServiceVersionProperties,)
from PB.recipes.chromeos.test_platform.cros_test_platform import (
    CrosTestPlatformProperties,)
from PB.recipes.chromeos.test_platform.cros_test_postprocess import (
    CrosTestPostprocessRequest,)
from PB.recipes.chromeos.test_platform.cros_test_postprocess import (
    TestResult as PostProcessTestResult,)
from PB.test_platform.result_flow import publish
from PB.test_platform.result_flow import common
from PB.test_platform import service_version as service_version_pb
from PB.test_platform.config.config import Config
from PB.test_platform.request import Request
from PB.test_platform.steps.enumeration import EnumerationRequest
from PB.test_platform.steps.enumeration import EnumerationRequests
from PB.test_platform.steps.enumeration import EnumerationResponse
from PB.test_platform.steps.enumeration import EnumerationResponses
from PB.test_platform.steps.execute.build import Build
from PB.test_platform.steps.execution import ExecuteRequest
from PB.test_platform.steps.execution import ExecuteRequests
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.steps.execution import ExecuteResponses
from PB.test_platform.taskstate import TaskState
from recipe_engine import post_process
from recipe_engine.post_process import GetBuildProperties
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/random',
    'recipe_engine/raw_io',
    'recipe_engine/resultdb',
    'recipe_engine/service_account',
    'recipe_engine/step',
    'recipe_engine/time',
    'bot_cost',
    'ctpv2',
    'cros_infra_config',
    'cros_history',
    'cros_resultdb',
    'cros_tags',
    'cros_test_platform',
    'cros_test_sharding',
    'cros_tool_runner',
    'easy',
    'future_utils',
    'result_flow',
    'satlab',
    'service_version',
    'skylab_results',
]

# Each CIPD package instance of cros_test_platform that has been promoted to
# staging or prod is tagged with a timestamped release version.
CTP_RELEASE_VERSION_TAG = 'ctp_release_version'
PROPERTIES = CrosTestPlatformProperties

BUILD_ID_REGEX = re.compile(r'\/b(?P<build_id>[0-9]+)$')
MAX_IN_SHARD = 70
CENTRALIZED_SUITE_PREFIX = 'centralizedsuite:'


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
      validation_errors.append(_validate_container_metadata_url(api, requests))
    if any(validation_errors):
      raise api.step.StepFailure('request validation failed')

  return requests


def _validate_container_metadata_url(api, requests):
  """Validate container metadata is provided if run_via_cft is set.

  Returns: True if requests are valid, False otherwise.
  """
  validation_error = False
  with api.step.nest('container metadata url') as step:
    for t, r in requests.items():
      if r.params.run_via_cft and not r.params.metadata.container_metadata_url:
        step.presentation.logs[
            t] = 'Error in container_metadata_url: %s' % 'container metadata url is required for CFT test request.'
        validation_error = True

    if validation_error:
      step.presentation.status = api.step.FAILURE
  return validation_error


def _validate_software_dependencies(api, requests):
  """Validate the software dependencies are internally consistent.

  Returns: True if requests are valid, False otherwise.
  """
  validation_error = False
  with api.step.nest('software dependencies') as step:
    for t, r in requests.items():
      errs = _invalid_software_dependencies(r.params.software_dependencies)
      if errs:
        step.presentation.logs[
            t] = 'Errors in software_dependencies: %s' % ', '.join(
                sorted(errs))
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
    for t, r in requests.items():
      request_timeout = r.params.time.maximum_duration
      if request_timeout is None:
        continue  # pragma: no cover

      request_timeout_s = request_timeout.ToTimedelta().total_seconds()
      if request_timeout_s > 0 and request_timeout_s >= max_timeout_s:
        step.presentation.logs[
            t] = 'Timeout (%s) is larger than maximum timeout (%s)' % (
                request_timeout.ToTimedelta(), max_timeout.ToTimedelta())
        step.presentation.status = api.step.FAILURE
        validation_error = True
  return validation_error


def _validate_scheduling_params(api, requests):
  """Validate scheduling parameters in the requests.

  Returns: True if requests are valid, False otherwise.
  """
  validation_error = False
  with api.step.nest('validate scheduling parameters') as step:
    for t, r in requests.items():
      error = _get_scheduling_error(r)
      if error:
        validation_error = True
        step.presentation.logs[t] = error
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
  return None


def enumerate_tests(api, properties, requests, error_in_requests):
  """Resolve request into list of tests and their metadata.

  Args:
    * api (object): See RunSteps documentation.
    * properties: Recipe input parameters.
    * requests: {tag: test_platform.Request} dict.
    * error_in_requests: {tag: error(str)} dict.

  Returns: {tag: EnumerationResponse} dict.
  """
  non_cft_requests = {
      t: r
      for t, r in requests.items()
      if t not in error_in_requests and not _should_enumerate_via_ctf(r)
  }
  cft_requests = {
      t: r
      for t, r in requests.items()
      if t not in error_in_requests and _should_enumerate_via_ctf(r)
  }
  # Fail build if no valid requests are found.
  if not (non_cft_requests or cft_requests):
    raise api.step.StepFailure('No valid request found')

  non_cft_enums = _enumerate_non_cft_tests(api, non_cft_requests)
  cft_enums = _enumerate_cft_tests(api, properties, cft_requests)

  all_enums = {}
  for k, v in non_cft_enums.items():
    all_enums[k] = v
  for k, v in cft_enums.items():
    all_enums[k] = v
  enmeration_responses_proto = EnumerationResponses(tagged_responses=all_enums)
  return enmeration_responses_proto.tagged_responses


# TODO(b/242007010): Remove this reconstruction.
# software_attributes.build_target are passed from skylab_board, which
# doesn't contain variant like -arc-r. metadata json are keyed with
# build target with varianed info.
# So use softwareDependencies.chromeosBuild to reconstruct
# build_target.
def _reconstruct_build_target(r):
  """Reconstruct build_target with variant from chromeos_build.

  Args:
    * r: test_platform.Request

  Returns: str or None
  """
  # If build_target is provided via keyvals, use it.
  if r.params.decorations.autotest_keyvals:
    build_target = r.params.decorations.autotest_keyvals.get('build_target')
    if build_target:
      return build_target

  # Otherwise constrcut build_target.
  dep = None
  for dep in r.params.software_dependencies:
    if dep.WhichOneof('dep') == 'chromeos_build':
      dep_parts = dep.chromeos_build.split('/')[0].split('-')
      # Strip postfixes that aren't included in the build_target.
      if dep_parts[-1] in ['main']:
        dep_parts = dep_parts[:-1]
      dep_parts = dep_parts[:-1]
      # Strip prefixes that aren't included in build_target.
      if dep_parts[0] in ['staging', 'dev']:
        dep_parts = dep_parts[1:]
      dep = '-'.join(dep_parts)
      break
  return dep


def _should_enumerate_via_ctf(r):
  """Whether the given request should be enumerated via cros-test-finder.

  Args:
    * r: test_platform.Request

  Returns: bool
  """
  return r.params.run_via_cft and _build_supports_cros_test_finder(r)


def _stage_builds_for_partners(api, requests):
  """Attempt to use the Moblab API to stage builds to a partners' bucket.

  Will not block recipe execution on failure.

  Args:
    * api (object): See RunSteps documentation.
    * requests: {tag: test_platform.Request} dict.
  """
  builds, bucket = _extract_builds_to_stage(requests)
  if not builds:
    return
  with api.step.nest('staging requested build(s)'):
    for build in builds:
      try:
        with api.step.nest(f'staging {build}'):
          api.satlab.stage_build(build, bucket)
      except:  # pylint: disable=W0702
        continue


def _extract_builds_to_stage(requests):
  """Determines which builds (if any) to stage.

  Args:
    * requests: {tag: test_platform.Request} dict.

  Returns: set(str) - set of builds, str - bucket
  """
  builds = set()
  for _, r in requests.items():
    bucket = _extract_bucket_from_request(r)
    if bucket and bucket != 'chromeos-image-archive':
      build = _extract_build_from_request(r)
      if build:
        builds.add(build)
  # just use the last bucket since they in theory should be the same.
  return builds, bucket


# pylint: disable=inconsistent-return-statements
def _extract_build_from_request(r):
  """Extracts the build in a test_platform request

  Args:
    * r: test_platform.Request

  Returns: str
  """
  for dep in r.params.software_dependencies:
    if dep.WhichOneof('dep') == 'chromeos_build':
      return dep.chromeos_build


def _extract_bucket_from_request(r):
  """Extracts the bucket in a test_platform request

  Args:
    * r: test_platform.Request

  Returns: str
  """
  for dep in r.params.software_dependencies:
    if dep.WhichOneof('dep') == 'chromeos_build_gcs_bucket':
      return dep.chromeos_build_gcs_bucket
  return None


def _extract_build_numbers_from_request(r):
  """Extracts the build number matches a test_platform request

  Args:
    * r: test_platform.Request

  returns List[string]
  """
  for dep in r.params.software_dependencies:
    if dep.WhichOneof('dep') == 'chromeos_build':
      return re.findall(r'/R(\d{2,3})-\d*', dep.chromeos_build)
  return []  # pragma: no cover


# TODO(b/261051011): Remove this workaround.
def _build_supports_cros_test_finder(r):
  """Whether the given request supports cros-test-finder enumeration; only
  R104 and newer support it.

  Args:
    * r: test_platform.Request

  Returns: bool
  """
  build_number_matches = _extract_build_numbers_from_request(r)
  if build_number_matches:
    return int(build_number_matches[0]) >= 104
  return False  # pragma: no cover


# TODO(b/265483258): Remove this once LTS hits 108.
def _should_cft_be_turned_off_for_build(r):
  """Whether the given request supports turning off cft. As all Rubik builds
  supports container creation and 108 is the first milestone that is full rubik,
  any build < 108 should support turning off cft (if necessary) in CTP.

  Args:
    * r: test_platform.Request

  Returns: bool
  """
  build_number_matches = _extract_build_numbers_from_request(r)
  if build_number_matches:
    return int(next(iter(build_number_matches), 108)) < 108
  return False  # pragma: no cover


def _enumerate_non_cft_tests(api, requests):
  """Resolve non-CFT requests into list of tests and their metadata.

  Args:
    * api (object): See RunSteps documentation.
    * requests: {tag: test_platform.Request} dict.

  Returns: {tag: EnumerationResponse} dict.
  """
  if not requests:
    return {}
  with api.step.nest('enumerate tests') as step:
    enum_requests = EnumerationRequests(
        tagged_requests={
            t: EnumerationRequest(
                metadata=r.params.metadata,
                test_plan=r.test_plan,
            ) for t, r in requests.items()
        })

    enum_responses = api.cros_test_platform.enumerate(enum_requests)
    for tag, response in sorted(enum_responses.tagged_responses.items()):
      _log_enumeration_errors(api, response, tag)
      name = 'autotest tests for %s' % tag
      step.presentation.logs[name] = json.dumps(
          _enumeration_log(response), separators=(',', ': '), indent=2,
          sort_keys=True)
    return dict(enum_responses.tagged_responses)


def _enumerate_cft_tests(api, properties, requests):
  """Resolve CFT requests into list of tests and their metadata.

  Args:
    * api (object): See RunSteps documentation.
    * properties: Recipe input parameters.
    * requests: {tag: test_platform.Request} dict.

  Returns: {tag: EnumerationResponse} dict.
  """
  if not requests:
    return {}
  tagged_responses = {}
  taggged_responses_json = {}
  with api.step.nest('enumerate CFT tests') as step:
    for t, r in requests.items():
      api.cros_tool_runner.create_file_with_container_metadata(
          r.params.execution_param.container_metadata)

      # We will have to run under the assumption that each request in the
      # CTP request will only have _either_ one test, or suite
      # even though the proto allows for both.
      args = _test_args_from_request(r)

      # TODO(b/242007010): Change back to use build_target.
      # See more details in the other comment about b/242007010 in this
      # file.
      # build_target = r.params.software_attributes.build_target.name
      build_target = _reconstruct_build_target(r)
      ctr_test_finder_request = ctr.CrosToolRunnerTestFinderRequest(
          request=_test_finder_request(r), container_metadata_key=build_target)
      test_finder_result = api.cros_tool_runner.find_tests(
          ctr_test_finder_request)

      suite_name = ''
      if r.test_plan.suite:
        suite_name = r.test_plan.suite[0].name

      autotest_invocations = []
      tag_criteria = r.test_plan.tag_criteria

      # Is singular in practice, even though its a list. This is because the
      # test_finder_request is being built from 1 request (r).
      # this needs to remain singular for downstream assumptions to work.
      test_suites = test_finder_result.test_suites
      if tag_criteria and (tag_criteria.tags or tag_criteria.tag_excludes):
        if api.cq.active:
          dry_run = True
          if ('chromeos.cros_infra_config.filtering_enabled'
              in api.cros_infra_config.experiments):
            dry_run = False  # pragma: no cover
          filtered_test_suites, removed_test_case_ids = _build_filtered_tests(
              api, r, test_suites, build_target, dry_run, suite_name)
          if not dry_run:  # pragma: no cover
            test_suites = filtered_test_suites
            _upload_filtered_test_cases_async(api, r, removed_test_case_ids)

        autotest_invocations = _build_tast_invocations(api, properties, r,
                                                       test_suites, suite_name,
                                                       args)
      elif r.test_plan.enable_autotest_sharding:
        # Sort test cases into test suites to be sharded or skipped based on whether their IDs start with 'tauto.tast'.
        test_cases_skip_shard = []
        test_cases_shard_eligible = []

        for test_suite in test_finder_result.test_suites:
          for test_case in test_suite.test_cases.test_cases:
            if test_case.id.value.startswith('tauto.tast'):
              test_cases_skip_shard.append(test_case)  # pragma: no cover
            else:
              test_cases_shard_eligible.append(test_case)

        test_suites_shard_eligible = [
            ctr_test_suite.TestSuite(
                test_cases=ctr_test_case.TestCaseList(
                    test_cases=test_cases_shard_eligible))
        ]
        test_suites_skip_sharding = [
            ctr_test_suite.TestSuite(
                test_cases=ctr_test_case.TestCaseList(
                    test_cases=test_cases_skip_shard))
        ]

        autotest_invocations_sharded = _build_tast_invocations(
            api, properties, r, test_suites_shard_eligible, suite_name, args)
        autotest_invocations_unsharded = _build_autotest_invocations(
            test_suites_skip_sharding, suite_name, args)

        autotest_invocations = autotest_invocations_sharded + autotest_invocations_unsharded

      else:
        autotest_invocations = _build_autotest_invocations(
            test_suites, suite_name, args)
      if autotest_invocations:
        tagged_responses[t] = EnumerationResponse(
            autotest_invocations=autotest_invocations)
        taggged_responses_json[t] = json_format.MessageToDict(
            tagged_responses[t])
      else:
        tagged_responses[t] = EnumerationResponse(error_summary='no test found')
        taggged_responses_json[t] = json_format.MessageToDict(
            tagged_responses[t])

    for tag, response in sorted(tagged_responses.items()):
      _log_enumeration_errors(api, response, tag)
      name = 'autotest tests for %s' % tag
      step.presentation.logs[name] = json.dumps(
          _enumeration_log(response), separators=(',', ': '), indent=2,
          sort_keys=True)

    step.presentation.logs['constructed cft enumeration response'] = json.dumps(
        taggged_responses_json, separators=(',', ': '), indent=2,
        sort_keys=True)

    return tagged_responses


def _upload_filtered_test_cases_async(api, req, tests):  # pragma: nocover
  """Upload filtered test cases to rdb, async.

  Args:
    * api: (object): See RunSteps documentation.
    * r: test_platform.Request.
    * tests: (List[str]): Test cases to be filtered.

  Returns: None
  """

  def _upload_filtered_test_cases(r):  # pragma: nocover
    """Upload filtered test cases to rdb.

    Args:
      * r: (Tuple(object, test_platform.Request, List[str]))

    Returns: None
    """
    api, req, tests = r
    try:
      base_tags, base_variant = _build_rdb_base_variant_and_tags(api, req)
      api.cros_resultdb.report_filtered_test_cases(
          tests, base_variant, base_tags,
          'filtered due to not meeting stability requirements')
    # Ensure filtered upload is non-breaking
    except Exception as e:  # pragma: nocover # pylint: disable=broad-except
      step.presentation.logs['Exception'] = json.dumps({'exception': str(e)},
                                                       separators=(',', ': '),
                                                       indent=2)

  if not tests:
    return
  with api.step.nest('Upload filtered test cases (async)') as step:
    runner = api.future_utils.create_parallel_runner()
    runner.run_function_async(lambda r, _: _upload_filtered_test_cases(r),
                              (api, req, tests))


def _build_rdb_base_variant_and_tags(api, req):  # pragma: nocover
  """Build variant and tags for rdb upload.

  Args:
    * api: (object): See RunSteps documentation.
    * r: test_platform.Request.

  Returns: List[test_suite], List[test_case_id]
  """
  queued_time = datetime.datetime.utcfromtimestamp(
      api.buildbucket.build.create_time.seconds)
  base_tags = [('is_cft_run', 'True'),
               ('queued_time', queued_time.strftime('%Y-%m-%d %H:%M:%S.%f UTC'))
              ]
  base_variant = {}
  tags = req.params.decorations.tags
  keyvals = req.params.decorations.autotest_keyvals
  if keyvals and 'build_target' in keyvals:
    base_variant['build_target'] = keyvals['build_target']
  if not tags:
    return base_tags, base_variant
  tags_dict = {}
  for tag in tags:
    parts = tag.split(':')
    if len(parts) == 2:
      if parts[0] not in tags_dict:
        tags_dict[parts[0]] = []
      tags_dict[parts[0]].append(parts[1])
  if 'label-board' in tags_dict:
    base_tags.append(('board', tags_dict['label-board'][0]))
    base_variant['board'] = tags_dict['label-board'][0]
  if 'label-model' in tags_dict:
    base_tags.append(('model', tags_dict['label-model'][0]))
    base_variant['model'] = tags_dict['label-model'][0]
  if 'label-pool' in tags_dict:
    base_tags.append(('label_pool', tags_dict['label-pool'][0]))
  if 'suite' in tags_dict:
    base_tags.append(('suite', tags_dict['suite'][0]))
  if 'build' in tags_dict:
    base_tags.append(('image', tags_dict['build'][0]))
    base_tags.append(('build', tags_dict['build'][0].split('/')[-1]))
  return base_tags, base_variant


def _build_filtered_tests(api, r, test_suites, build_target, dryrun,
                          suite_name):
  """Create non-breaking step to filter out test cases.

  Args:
    * r: test_platform.Request.
    * test_suites: List[test_suite]
    * build_target: board
    * dryrun: bool
    * suite_name: string

  Returns: List[test_suite], List[test_case_id]
  """
  with api.step.nest('filter test cases') as step:
    try:
      build_number_matches = _extract_build_numbers_from_request(r)
      milestone = next(iter(build_number_matches))
      cfg = api.cros_infra_config.get_test_filter_config()
      step.presentation.logs['cfg_used'] = json_format.MessageToJson(cfg)

      req = _ctr_test_filter(test_suites, build_target, milestone, dryrun, cfg,
                             str(api.buildbucket.build.id), suite_name)
      # If no req, do not call the service, just return with no filtering done.
      # This will happen when a suite opts out.
      if not req:  # pragma: no cover
        return test_suites, []
      step.presentation.logs['policy_used'] = json_format.MessageToJson(req)
      pre_test_resp = api.cros_tool_runner.pre_process(req)
      if pre_test_resp.response.removed_tests:  # pragma: no cover
        removed = [str(test) for test in pre_test_resp.response.removed_tests]
        step.presentation.logs['removed_tests'] = json.dumps(
            {'removed': removed}, separators=(',', ': '), indent=2)
        return pre_test_resp.response.test_suites, removed  # pragma: no cover
      return test_suites, []

    # Ensure step is non-breaking
    except Exception as e:  # pragma: nocover # pylint: disable=broad-except
      step.presentation.logs['Exception'] = json.dumps({'exception': str(e)},
                                                       separators=(',', ': '),
                                                       indent=2)
      return test_suites, []


def _build_tast_invocations(api, properties, request, test_suites, suite_name,
                            args):
  """Creates a list of EnumerationResponse.AutotestInvocation with logic for tast such as bucketing and sharding.

  Args:
    * api: Modules for loaded recipe DEPS
    * properties: Recipe input parameters.
    * request: test_platform.Request
    * test_suites: List[test_suite].
    * suite_name: string.
    * args: string.

  Returns: List[EnumerationResponse.AutotestInvocation].
  """
  with api.step.nest('Shard test cases') as step:
    seed = request.test_plan.seed
    total_shards = request.test_plan.total_shards
    max_in_shard = request.test_plan.max_in_shard
    if max_in_shard == 0:
      max_in_shard = MAX_IN_SHARD
    # TODO (b/272816888): Short term experiment, replace with value from configs later.
    if suite_name.__contains__('tast-tags-test-suite'):  # pragma: no cover
      if request.test_plan.tag_criteria.test_names:
        if request.test_plan.tag_criteria.test_names[0] == 'tast.arc.*':
          max_in_shard = 100
        elif request.test_plan.tag_criteria.test_names[0] == 'tast.crostini.*':
          max_in_shard = 40
      else:
        max_in_shard = 225
    if seed is None or seed == 0:
      seed = int(api.time.time())
    step.presentation.logs['shard seed'] = json.dumps({'seed': seed},
                                                      separators=(',', ': '),
                                                      indent=2)
    api.random.seed(seed)
    autotest_invocations = []
    for test_suite in test_suites:
      test_buckets = []
      if (suite_name in {
          'bvt-tast-cq', 'bvt-tast-cq-hw', 'bvt-tast-cq-hw-agnostic',
          'cq-medium'}) \
          and \
          ('chromeos.cros_infra_config.optimized_shard_allocation' in
           api.cros_infra_config.experiments or
           CrosTestPlatformProperties.OPTIMIZED_SHARDING in
           properties.experiments):
        shards = api.cros_test_sharding.optimized_shard_allocation(
            test_suite, total_shards)
      else:
        test_buckets = _bucket_by_dependencies(
            list(test_suite.test_cases.test_cases), suite_name)
        shards = _shard_test_buckets(api, test_buckets, total_shards,
                                     max_in_shard)
      step.presentation.tags['shard_count'] = str(len(shards))
      step.presentation.tags['unique_dependencies_count'] = str(
          len(test_buckets))
      for i, shard in enumerate(shards):
        shard_name = '%s-shard-%d' % (suite_name, i)
        test_names = [test_case.id.value for test_case in shard]
        shard_dependencies = _shard_dependencies(shard)
        step.presentation.logs[shard_name] = json.dumps(
            {
                'shardName': shard_name,
                'dependencies': shard_dependencies,
                'testNames': test_names,
            }, separators=(',', ': '), indent=2)
        autotest_invocation = EnumerationResponse.AutotestInvocation(
            test=test_metadata.AutotestTest(
                name=shard_name,
                names=test_names,
                dependencies=[
                    test_metadata.AutotestTaskDependency(label=dep)
                    for dep in shard_dependencies
                ],
                execution_environment=1,
                # TODO (b/254684984): Remove these default values in long term
                allow_retries=True,
                max_retries=1,
            ),
            result_keyvals={'suite': suite_name},
            test_args=args,
        )
        autotest_invocations.append(autotest_invocation)
    return autotest_invocations


def _build_autotest_invocations(test_suites, suite_name, args):
  """Creates a list of EnumerationResponse.AutotestInvocation with logic for autotest.

  Args:
    * test_suites: List[test_suite].
    * suite_name: string.
    * args: string.

  Returns: List[EnumerationResponse.AutotestInvocation].
  """

  autotest_invocations = []
  for test_suite in test_suites:
    for test_case in test_suite.test_cases.test_cases:
      autotest_invocation = EnumerationResponse.AutotestInvocation(
          test=test_metadata.AutotestTest(
              name=test_case.id.value,
              dependencies=[
                  test_metadata.AutotestTaskDependency(label=dep.value)
                  for dep in test_case.dependencies
              ],
              execution_environment=1,
              # TODO (b/254684984): Remove these default values in long term
              allow_retries=True,
              max_retries=1,
          ),
          result_keyvals={'suite': suite_name},
          test_args=args)
      autotest_invocations.append(autotest_invocation)
  return autotest_invocations


def _bucket_by_dependencies(test_cases, suite_name):
  """Creates a list of buckets grouping test_cases by their dependencies.

  Args:
    * test_cases: List[test_case].
    * suite_name: string.

  Returns: List[List[test_case]].
  """
  bucket = {}

  skipDeps = False
  # Currently due to the size of these suites, sharding them into buckets on
  # deps could result in dozens to hundreds of devices, including those
  # with exceptionally high pending time. For now, they will be ignored,
  # like they have been for the past decade.
  if suite_name in {
      'bvt-tast-cq', 'bvt-tast-cq-hw', 'bvt-tast-cq-hw-agnostic',
      'bvt-tast-informational', 'cq-medium', 'bvt-tast-criticalstaging'
  }:  # pragma: no cover
    skipDeps = True
  for test_case in test_cases:
    # TODO (b/277945083): Hard code to group tast.security tests together.
    # Remove once long term solution is implemented.
    if 'tast.security' in test_case.id.value:  # pragma: no cover
      security_bucket = '__SECURITY__'
      if security_bucket not in bucket:
        bucket[security_bucket] = []
      bucket[security_bucket].append(test_case)
      continue

    deps = frozenset()
    if not skipDeps:
      deps = frozenset(list(dep.value for dep in test_case.dependencies))
    if deps in bucket:
      bucket[deps].append(test_case)
    else:
      bucket[deps] = [test_case]
  return list(bucket.values())


def _shard_test_buckets(api, test_buckets, total_shards, max_in_shard):
  """Distribute shards among the pool of test_buckets and shard their test cases.

  If total_shards is non-zero, run through the distribution logic.
  Each bucket will receive a number of shards from the total_shards value
  proportional to their number of test cases as compared to the total number
  of test cases. Start with the smallest buckets to ensure they receive at
  least one shard allocated.

  Example:
    Bucket 1: 1 test
    Bucket 2: 40 tests
    Bucket 3: 50 tests
    total_shards: 4

    Bucket 1 is smallest. Take its test_cases ratio of 1/99 and multiply by the available shards 4.
    Bucket 1 gets 1 shard and removes its shard and test_cases count from the total counts.
    Bucket 2 is next smallest. Take its test_cases ratio of 40/90 and multiply by the available shards 3.
    Bucket 2 gets 1 shard and removes its shard and test_cases count from the total counts.
    Bucket 3 is last. Take its test_cases ratio of 50/50 and multiply by the available shards 2.
    Bucket 3 gets 2 shard and removes its shard and test_cases count from the total counts.

  Args:
    * test_buckets: List[List[api.TestCase]]
    * total_shards: int
    * max_in_shard: int

  Returns: List[List[api.TestCase]].
  """
  shards = []
  if total_shards != 0:
    total_shards = max(total_shards, len(test_buckets))
  num_test_cases_left_to_shard = sum(len(bucket) for bucket in test_buckets)
  total_shards_left = total_shards
  # Sorted for largest buckets first. Ensures that shards allocated is always non-zero.
  test_buckets.sort(key=len)
  for bucket in test_buckets:
    if total_shards != 0:
      shards_allocated = max(
          1,
          math.floor(
              (len(bucket) / num_test_cases_left_to_shard) * total_shards_left))
      num_test_cases_left_to_shard -= len(bucket)
      total_shards_left -= shards_allocated
      max_in_shard = math.ceil(len(bucket) / shards_allocated)
    shards.extend(_shard_test_cases(api, bucket, max_in_shard))
  return shards


def _shard_test_cases(api, test_cases, max_in_shard=MAX_IN_SHARD):
  """Create groupings of the test_cases.

  Args:
    * test_cases (test_cases: List[api.TestCase]): See RunSteps documentation.

  Returns: List[List[api.TestCase]].
  """
  api.random.shuffle(test_cases)
  num_shards = math.ceil(len(test_cases) / max_in_shard)
  num_in_shard = int(len(test_cases) / num_shards)

  res = []
  start = 0
  for _ in range(num_shards):
    res.append(test_cases[start:start + num_in_shard])
    start += num_in_shard

  leftover = test_cases[start:]
  for i, test_case in enumerate(leftover):
    res[i].append(test_case)

  return res


def _shard_dependencies(shard):
  """Creates a set of dependencies from the shard's test cases.

  Args:
    * shard: List[test_case].

  Returns: List[test_case.dependency].
  """
  deps = set()
  for test_case in shard:
    for dep in test_case.dependencies:
      deps.add(dep.value)
  return list(deps)


def _ctr_test_filter(test_suites, board, milestone, dryrun, cfg, bbid=None,
                     suite_name=''):
  """Build a CrosToolRunnerPreTestRequest.

  Args:
    * test_suites: List[TestSuite]
    * board: board
    * milestone: string
    * dryrun: bool, if the mode is being set as a dryrun from CTP.
    * cfg: api.FilterCfgs
    * bbid: str, bbid of the task
    * suite_name: str, the current suite_name

  Returns: ctr.CrosToolRunnerPreTestRequest
  """
  if not cfg:
    return None  # pragma: no cover

  globalcfg = None
  localcfg = None

  # Loop through the cfg, and look for the first policy match.
  for policy in cfg.filter_cfg:
    if policy.test_suites == ['*']:
      globalcfg = policy.pass_rate_policy
    else:
      if suite_name in policy.test_suites:  # pragma: no cover
        if policy.opt_out:
          return None
        localcfg = policy.pass_rate_policy
        break

  # If a policy is not found, use the global policy.
  if not localcfg:
    localcfg = globalcfg

  # If for some reason there is no global found, its safer just to
  # not filter at all
  if not localcfg:
    return None  # pragma: no cover

  localcfg.dryrun = dryrun

  formattedProto = pre_request.FilterFlakyRequest(
      pass_rate_policy=localcfg, board=board, test_suites=test_suites,
      milestone=milestone, default_enabled=True, bbid=bbid)
  return ctr.CrosToolRunnerPreTestRequest(request=formattedProto,
                                          container_metadata_key=board)


def _test_args_from_request(request):
  """Return the args to be used in the run, set in the request.

  Args:
    * request: test_platform.Request

  Returns: string
  """

  # We will always 0 index.
  # Mostly because the combination of every CTP request is always only 1 test
  # or suite. Additionally; this is just for short-term support until CTPv2.
  if request.test_plan.test:
    if request.test_plan.test[0].autotest.test_args:
      return request.test_plan.test[0].autotest.test_args  # pragma: nocover
  elif request.test_plan.suite:
    return request.test_plan.suite[0].test_args
  return ''


def _test_finder_request(request):  # pragma: nocover
  """Generates a test finder request that resolves suites in the CTP request."""
  if _is_centralized_suite(request):
    raw_suite = request.test_plan.suite[0].name
    centralized_suite = raw_suite.removeprefix(CENTRALIZED_SUITE_PREFIX)
    return ctf.CrosTestFinderRequest(centralized_suite=centralized_suite)

  return ctf.CrosTestFinderRequest(test_suites=[_ctr_test_suite(request)])


def _is_centralized_suite(request):  # pragma: nocover
  """Returns True if the request contains a centralized suite, else False."""
  suite_list = request.test_plan.suite
  return suite_list and len(suite_list) == 1 and \
    suite_list[0].name.startswith(CENTRALIZED_SUITE_PREFIX)


def _ctr_test_suite(request):
  """Build a CrosToolRunnerTestFinderRequest from a list of test requests.

  Args:
    * request: test_platform.Request

  Returns: ctr.TestSuite
  """

  if request.test_plan.test:
    return ctr_test_suite.TestSuite(
        test_case_ids=ctr_test_case.TestCaseIdList(test_case_ids=[
            ctr_test_case.TestCase.Id(value=t.autotest.name)
            for t in request.test_plan.test
        ]))

  tags = []
  tag_excludes = []
  test_names = []
  test_name_excludes = []
  tag_criteria = request.test_plan.tag_criteria
  if tag_criteria and (tag_criteria.tags or tag_criteria.tag_excludes or
                       tag_criteria.test_names or
                       tag_criteria.test_name_excludes):
    tags = tag_criteria.tags
    tag_excludes = tag_criteria.tag_excludes
    test_names = tag_criteria.test_names
    test_name_excludes = tag_criteria.test_name_excludes
  else:
    tags = ['suite:%s' % s.name for s in request.test_plan.suite]
  return ctr_test_suite.TestSuite(
      test_case_tag_criteria=ctr_test_suite.TestSuite.TestCaseTagCriteria(
          tags=tags, tag_excludes=tag_excludes, test_names=test_names,
          test_name_excludes=test_name_excludes))


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


def execute(api, properties, requests):
  """Execute request in the correct backend.

  Args:
    properties: CrosTestPlatformProperties
    requests: ExecutionRequests payload.
  """
  with api.step.nest('execute'):
    return api.cros_test_platform.execute_luciexe(properties, requests)


def _execute_requests(api, requests, enumerations, config, error_in_requests):
  """Create the request payload for execution.|
  Args:
    requests: {tag: test_platform.Request} dict.
    enumerations: {tag: EnumerationResponse} dict.
    config: test_platform.Config instance.
    error_in_requests: {tag: error(str)} dict.

  Returns:
    ExecutionRequests payload.
  """
  _ensure_all_requests_enumerated(requests, enumerations, error_in_requests)
  _limit_tests_retry(api, requests)
  return ExecuteRequests(
      tagged_requests={
          t: ExecuteRequest(request_params=r.params,
                            enumeration=enumerations[t], config=config)
          for t, r in requests.items()
          if t not in error_in_requests
      },
      build=Build(id=api.buildbucket.build.id,
                  create_time=api.buildbucket.build.create_time),
  )


def _limit_tests_retry(api, requests):
  """Limits the number of test retries:
    - Requests triggered by Suite scheduler are exempted
    - Requests triggered by crosfleet that have only one request name "default
      and the test suite name is "tast.lacros" are exempted
    - Requests marked as Critical are exempted
    - All other test have their retries disabled

  Args:
    * request: ExecutionRequests payload.
  """
  requests_user_agents = api.cros_tags.get_values('user_agent')
  # Suite scheduler are not limited
  if 'suite_scheduler' in requests_user_agents:
    return

  # Exception for tast.lacross tests scheduled via crosfleet as they are
  # critical but can't currently be marked as critical via the cros CLI
  if 'crosfleet' in requests_user_agents:
    if (len(requests) == 1 and 'default' in requests.keys() and
        len(requests['default'].test_plan.test) == 1 and
        requests['default'].test_plan.test[0].autotest.name == 'tast.lacros'):
      return

  for _, request in requests.items():
    if request.params.test_execution_behavior != Request.Params.TestExecutionBehavior.CRITICAL:
      request.params.retry.max = 0
      request.params.retry.allow = False


def _ensure_all_requests_enumerated(requests, enumerations, error_in_requests):
  missing = (set(requests.keys()) - set(error_in_requests.keys())) - set(
      enumerations.keys())
  if missing:
    raise StepFailure('No enumerations for requests tagged %s' %
                      sorted(missing))


def RunSteps(api, properties):
  with api.bot_cost.build_cost_context():
    DoRunSteps(api, properties)


def DoRunSteps(api, properties):
  # Log which cros_test_platform release version the tests will run on.
  output_ctp_release_timestamp_tag(api)
  api.easy.log_parent_step(log_if_no_parent=False)

  if properties.HasField(
      'ctpv2_request') and api.ctpv2.is_enabled():  # pragma: nocover
    # Use ctpv2 binary rather than the normal ctpv1 workflow.
    api.ctpv2.execute_luciexe()
    return

  # Check for any requests that qualify for
  # ctpv2 translation.
  ctp2_pools = api.cros_infra_config.get_ctp2_pools_config()
  api.ctpv2.set_allowed_pools(ctp2_pools)
  v2_request_count = len(api.ctpv2.filter_legacy_requests(properties.requests))
  if v2_request_count > 0:
    try:
      api.ctpv2.execute_luciexe(use_legacy=True)
    # pylint: disable=broad-except
    except Exception:
      pass
    if v2_request_count == len(properties.requests):
      return

  _top_level_export_to_bigquery(api, properties.force_export)
  if api.cq.active:
    api.easy.set_properties_step(is_retry=api.cros_history.is_retry)

  # Push Build ID to Pubsub to notify the subscribers that a new CTP
  # build is about to run.
  publish_to_result_flow(api, properties.config)
  requests = validated_requests(api, properties)
  with api.context(infra_steps=True):
    # {tag: error(str)} dict that will store error msg for respective tag.
    error_in_requests = {}
    add_container_metadata(api, requests, error_in_requests)
    _validate_request_error_and_turn_off_cft_if_necessary(
        api, requests, error_in_requests)
    _stage_builds_for_partners(api, requests)
    enumerations = enumerate_tests(api, properties, requests, error_in_requests)
    responses, suite_execution_logs = execute(
        api, properties,
        _execute_requests(api, requests, enumerations, properties.config,
                          error_in_requests))
    # Add error responses for each request that had error.
    # This is necessary so that output properties have all responses.
    responses = _append_error_responses(error_in_requests, responses)
    tagged_responses = responses.tagged_responses
    set_output_properties(api, responses)
    # Push the Build ID to notify the subscribers that test plan execution
    # is completed.
    publish_to_result_flow(api, properties.config,
                           should_poll_for_completion=True)

    postprocess(api, requests, tagged_responses,
                skip_postprocess=properties.partner_config)
  summarize(api, enumerations, tagged_responses, error_in_requests,
            suite_execution_logs)


def _append_error_responses(error_in_requests, responses):
  """Add error responses to test result responses.

  Args:
    * error_in_requests: {tag: error(str)} dict.
    * responses: ExecuteResponses.
  Returns:
    Updated ExecuteResponses.
  """
  responses_dict = json_format.MessageToDict(responses)
  for t, _ in error_in_requests.items():
    responses_dict['taggedResponses'][t] = _error_response()
  return json_format.ParseDict(responses_dict, ExecuteResponses())


def _error_response():
  """ExecuteResponse for error cases."""
  return json_format.MessageToDict(
      ExecuteResponse.TaskResult(
          state=TaskState(verdict='VERDICT_FAILED',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ))


def _validate_request_error_and_turn_off_cft_if_necessary(
    api, requests, error_in_requests):
  """validate request error and turn off cft if necessary.

  Args:
    * api (RecipeApi): Recipe api object.
    * requests: ExecuteRequests.tagged_requests.
    * error_in_requests: {tag: error(str)} dict.
  """
  # retrun if there was no container metadata error
  if not error_in_requests:
    return

  cft_turned_off_tags_list = []
  with api.step.nest('determine if cft should be turned off') as step:
    for t, _ in error_in_requests.items():
      if requests[t].params.run_via_cft and _should_cft_be_turned_off_for_build(
          requests[t]):
        # add to the list
        cft_turned_off_tags_list.append(t)
        # turn off cft
        requests[t].params.run_via_cft = False

    if cft_turned_off_tags_list:
      # Delete the entry from error dict so non-cft workflow picks this up
      for tag in cft_turned_off_tags_list:
        del error_in_requests[tag]

      # Log the tags and set step tags to be used for queries
      step.presentation.tags['cft_turned_off_tags_list'] = ','.join(
          cft_turned_off_tags_list)
      step.presentation.logs[
          'requests_for_which_cft_is_turned_off'] = '\n'.join(
              cft_turned_off_tags_list)
    else:
      step.presentation.logs[
          'summary'] = 'No requests were modified to turn off cft.'

  return


def add_container_metadata(api, requests, error_in_requests):
  """Add container metadata to requests when required.

  Args:
    * api (RecipeApi): Recipe api object.
    * requests: ExecuteRequests.tagged_requests.
    * error_in_requests: {tag: error(str)} dict.
  """
  # Multiple requests may have same container metadata.
  # Run time can be cut down by only downloading them once.
  unique_metadata_urls = list(
      set(r.params.metadata.container_metadata_url
          for r in requests.values()
          if r.params.run_via_cft))

  # No CFT requests defined. So no need to get and add container metadata.
  if not unique_metadata_urls:
    return

  url_to_metadata_map = {}
  url_to_error_map = {}
  with api.step.nest('retrieve container metadata') as step:
    step.presentation.logs[
        'unique container metadata urls in request'] = '/n'.join(
            unique_metadata_urls)
    for url in unique_metadata_urls:
      url_to_metadata_map[url] = _get_container_metadata(
          api, url, url_to_error_map)

  with api.step.nest('assign container metadata to requests') as step:
    for t, r in requests.items():
      error = ''
      if r.params.run_via_cft:
        with api.step.nest(t) as step:
          # TODO(b/242007010): Change back to use build_target.
          # See more details in the other comment about b/242007010 in this
          # file.
          # build_target = r.params.software_attributes.build_target.name
          build_target = _reconstruct_build_target(r)
          metadata_url = r.params.metadata.container_metadata_url
          metadata = url_to_metadata_map[metadata_url]
          if metadata:
            if build_target in metadata.containers:
              r.params.execution_param.container_metadata.CopyFrom(metadata)
              step.presentation.logs[
                  'container metadata'] = json_format.MessageToJson(metadata)
            else:
              error = "No container information found in container metadata for request '{}', build target '{}', container metadata url '{}'.".format(
                  t, build_target, metadata_url)
          else:
            error = url_to_error_map[metadata_url]

          if error:
            # mark this entry to be skipped so that enumeration and execution steps ignore this request.
            error_in_requests[t] = error
            step.presentation.logs['container metadata error'] = error


def _get_container_metadata(api, metadata_gs_url, url_to_error_map):
  """Get container metadata from GS.

  Args:
    * api (RecipeApi): Recipe api object.
    * metadata_gs_url (str): ExecuteRequests.tagged_requests.
    * url_to_error_map: {tag: error(str)} dict.
  Returns:
    Container metadata if successully retrieved. Otherwise None.
  """
  metadata = None
  with api.step.nest('get container metadata from GS') as step:
    # Retrieve container metadata and log any parsing errors that occur,
    # but don't allow it to fail the overall build.
    try:
      cat_res = api.gsutil.cat(metadata_gs_url, infra_step=True,
                               name='cat {}'.format(metadata_gs_url),
                               stdout=api.raw_io.output(add_output_log=True))
      res = cat_res.stdout
      metadata = json_format.Parse(res, ContainerMetadata())
    # pylint: disable=broad-except
    except Exception as ex:
      step.presentation.logs['container metadata error'] = str(ex)
      url_to_error_map[
          metadata_gs_url] = 'Error while retrieving container metadata from {}: {}'.format(
              metadata_gs_url, str(ex))
      step.status = api.step.FAILURE

  return metadata


def _build_has_ancestor(api):
  """Determine whether the current build has any ancestor."""
  return bool(api.buildbucket.build.ancestor_ids)


# TODO(b/234080013): Restore the default value of False to
# `skip_postprocess` once the logic works correctly.
def postprocess(api, requests, responses, skip_postprocess=True):
  with api.step.nest('postprocess') as step:
    # For partner build configs, don't schedule cros_test_postprocess builds.
    if skip_postprocess:
      step.presentation.step_summary_text = 'Skipped: Postprocess disabled'
      return
    for tag, response in sorted(responses.items()):
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

  # There were no tests attempted for the suite (e.g. enumeration errors).
  if not consolidated_results:
    return _REQUEST_INCOMPLETE_FAILURE

  for result in consolidated_results:
    if all(t.state.life_cycle == TaskState.LIFE_CYCLE_REJECTED
           for t in result.attempts):
      return _REQUEST_REJECTED_PARAMETERS
    if all(_is_incomplete_result(t) for t in result.attempts):
      # If any enumeration only produced incomplete results, the entire request
      # will be classified as incomplete, so we don't have to continue looking
      # at the other results.
      return _REQUEST_INCOMPLETE_FAILURE

  # If no failures with incomplete results or rejected parameters are detected,
  # then we can say the request failed with complete results.
  return _REQUEST_FAILURE


def summarize(api, enumerations, responses, error_in_requests,
              suite_execution_logs):
  # Failures in summarization are non-infra related.
  failures = 0

  request_classifications = collections.OrderedDict()
  for state in _REQUEST_STATES:
    request_classifications[state] = 0

  with api.step.nest('summarize') as step:
    if suite_execution_logs:
      with api.step.nest('execution logs') as log_step:
        # Log the suite execution metrics
        for key in suite_execution_logs:
          if key == 'totals':
            log_step.logs[
                'Total Per Suite Execution Statistics'] = suite_execution_logs[
                    key]
          else:
            log_step.logs[key + ' execution logs'] = suite_execution_logs[key]

    for tag, response in sorted(responses.items()):
      with api.step.nest('%s task results' % tag) as results_step:
        if 'totals' in suite_execution_logs:  # pragma: nocover
          ioStringReader = StringIO(suite_execution_logs['totals'])
          reader = csv.DictReader(ioStringReader)
          for row in reader:
            if row['suiteName'] == tag and row['exceededExecutionLimit'].lower(
            ) == 'true':
              if row['exceptionGranted'].lower() == 'true':
                results_step.step_summary_text = 'SuiteLimits: Execution limit exceeded, but exception granted. No action taken.'
              else:
                results_step.step_summary_text = 'SuiteLimits: Execution limit exceeded: go/suitelimits-faqs'

        if tag in error_in_requests:
          _log_error_in_request(api, tag, error_in_requests[tag])

        _log_enumeration_errors(api, enumerations[tag], tag)
        _log_task_results(api, response.task_results)
        if response.state.verdict in _SUCCESSFUL_VERDICTS:
          request_classifications[_REQUEST_SUCCESS] += 1
        else:
          failures += 1
          step.logs['overall verdict'] = TaskState.Verdict.Name(
              response.state.verdict)
          classification = _classify_request_failure(
              response.consolidated_results)
          request_classifications[classification] += 1
          step.presentation.status = api.step.FAILURE

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
        "Please `skylab update` and try again. If you're stuck on this, "
        'please see http://go/skylab-cli')
  if not properties.requests:
    raise api.step.StepFailure(
        'Must set "requests" in input properties (found %s)' %
        properties.requests)
  return api.ctpv2.filter_legacy_requests(properties.requests, reverse=True)


def _top_level_export_to_bigquery(api, force_export):
  if not api.resultdb.enabled:
    return

  # Skips the BigQuery export step if the current build has any ancestor (unless
  # force_export is set to true, in which case we export anyways).
  if not force_export and _build_has_ancestor(api):
    return
  with api.step.nest('configure resultdb bigquery export'):
    bigquery_export = invocation_pb2.BigQueryExport(
        project='cros-test-analytics', dataset='resultdb', table='test_results',
        test_results=invocation_pb2.BigQueryExport.TestResults())
    api.cros_resultdb.export_invocation_to_bigquery([bigquery_export])


def set_output_properties(api, responses):
  """Set the output properties that are part of the cros_test_platform API."""
  with api.step.nest('set output properties') as step:
    step.presentation.logs['output'] = json_format.MessageToJson(responses)
    marshalled = api.skylab_results.test_api.marshal_responses(responses)
    # Requests that specify a single request instead of a multi-request result
    # in a response tagged 'default'. Some clients that specify a single
    # request cannot handle compressed responses, see crbug.com/1086075 or
    # http://b/187792377.
    if 'default' in marshalled:
      step.properties['response'] = json.dumps(marshalled['default'],
                                               separators=(',', ': '), indent=2,
                                               sort_keys=True)

    step.properties[
        'compressed_responses'] = api.skylab_results.test_api.base64_compress_proto(
            responses).decode('utf-8')
    step.properties[
        'compressed_json_responses'] = api.skylab_results.test_api.base64_compress_dict(
            marshalled).decode('utf-8')


def _log_enumeration_errors(api, enum, tag):
  if enum.error_summary:
    with api.step.nest('enumeration error') as step:
      step.logs['summary'] = '{} : {}'.format(tag, enum.error_summary)
      step.presentation.status = api.step.FAILURE


def _log_error_in_request(api, tag, error):
  with api.step.nest('container metadata error') as step:
    step.logs['summary'] = '{} : {}'.format(tag, error)
    step.presentation.status = api.step.FAILURE


# The odd-looking string.replaced items below are listed as such to aid in code
# searchability. Users are most likely to search for these things after seeing
# them in Milo, and in Milo we display them with spaces rather than underscores.
_SUCCESSFUL_TASK_STATES = [
    state_string.replace(' ', '_') for state_string in [
        'passed',
        # Flakes are failed test runs that later succeed. e.g. if we run a test
        # and it fails, but then we retry it and the retry succeeds, we call the
        # first run a flake and the second run a pass.
        'flaked',
        'skipped',
    ]
]
_UNSUCCESSFUL_TASK_STATES = [
    state_string.replace(' ', '_') for state_string in [
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


def _log_task_results(api, unsorted_task_results):
  """Report task results for a request on the UI."""
  task_results_by_state = sort_task_results_by_state(unsorted_task_results)

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
  unsuccessful_at_least_once = []
  for tr in task_results:
    if tr.state.life_cycle == TaskState.LIFE_CYCLE_COMPLETED and tr.state.verdict in _PASSED_VERDICTS:
      task_results_by_state.passed.append(tr)
      continue
    # Don't assign state to unsuccessful tasks at this point, since we don't
    # know if they passed on retry or not.
    unsuccessful_at_least_once.append(tr)

  passed_set = {x.name for x in task_results_by_state.passed}
  for tr in unsuccessful_at_least_once:
    if tr.name in passed_set:
      task_results_by_state.flaked.append(tr)
      continue

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
      if tr.state.verdict == TaskState.VERDICT_NO_VERDICT:
        task_results_by_state.skipped.append(tr)
      elif tr.state.verdict in _FAILED_VERDICTS:
        task_results_by_state.failed_all_attempts.append(tr)
    else:  # pragma: no cover
      task_results_by_state.other.append(tr)

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

      _emit_link(step, '', 'task', t.name, t.task_url)

      continue
    suffix = ''
    if t.attempt > 0:
      suffix = ' attempt #%s' % str(t.attempt)
      if t.state.verdict in _PASSED_VERDICTS:
        suffix = suffix + ' passed on retry'
    _emit_link(step, '{}.'.format(str(i)), 'log', '{}{}'.format(t.name, suffix),
               t.log_url)
    _emit_link(step, '{}.'.format(str(i)), 'task',
               '{}{}'.format(t.name, suffix), t.task_url)


def _emit_link(step, prefix, link_name, task_name, link_url):
  """Emit link for valid link.

  Args:
    * step:  a recipe step.
    * prefix: prefix of the link text.
    * link_name: name of the entity which link is being emitted. ex: log, task etc.
    * task_name: task name. ex: name of the test.
    * link_url: link url.
  """
  if link_url:
    step.links['{} ({})  {}'.format(prefix, link_name, task_name)] = link_url
  else:
    step.links[
        '{prefix} ({link_name})  {task_name} (no {link_name} link)'.format(
            prefix=prefix, link_name=link_name,
            task_name=task_name)] = 'broken-link'


def _test_scheduling():
  return Request.Params.Scheduling(qs_account='foo-qs-account')


def _default_software_dependencies():
  return [
      Request.Params.SoftwareDependency(
          chromeos_build='staging-foo-build-target-postsubmit-main/R108-33333.0.0-112318231231',
      ),
      Request.Params.SoftwareDependency(
          ro_firmware_build='single-ro-firmware',
      ),
      Request.Params.SoftwareDependency(
          rw_firmware_build='single-rw-firmware',
      ),
  ]


def _different_bucket_software_deps(bucket):
  return [
      Request.Params.SoftwareDependency(
          chromeos_build='brya-release/R108-33333.222.111',
      ),
      Request.Params.SoftwareDependency(
          ro_firmware_build='single-ro-firmware',
      ),
      Request.Params.SoftwareDependency(
          rw_firmware_build='single-rw-firmware',
      ),
      Request.Params.SoftwareDependency(
          chromeos_build_gcs_bucket=bucket,
      ),
  ]


def _software_dependencies_with_milestone_before_108():
  return [
      Request.Params.SoftwareDependency(
          chromeos_build='foo-build-target-postsubmit/R107-33333.0.0-112318231231',
      ),
      Request.Params.SoftwareDependency(
          ro_firmware_build='single-ro-firmware',
      ),
      Request.Params.SoftwareDependency(
          rw_firmware_build='single-rw-firmware',
      ),
  ]


# pylint: disable=dangerous-default-value
def _test_request(request_name_tag, build_target='foo-build-target',
                  scheduling=_test_scheduling(), individual_test=False,
                  individual_test_name=None, tag_criteria=None, seed=None,
                  software_deps=_default_software_dependencies(), retries=0,
                  total_shards=0, suite_name=None,
                  enable_autotest_sharding=False, swarming_tags=[]):
  params = Request.Params(
      software_attributes=Request.Params.SoftwareAttributes(
          build_target=BuildTarget(
              name=build_target,
          )),
      decorations=Request.Params.Decorations(
          tags=swarming_tags,
      ),
      hardware_attributes=Request.Params.HardwareAttributes(model='%s-model' %
                                                            request_name_tag),
      metadata=Request.Params.Metadata(
          test_metadata_url='gs://%s-metadata-url' % request_name_tag,
          debug_symbols_archive_url='gs://%s-metadata-url' % request_name_tag,
          container_metadata_url='gs://%s-container-metadata-url' %
          request_name_tag),
      scheduling=scheduling,
      software_dependencies=software_deps,
      retry=Request.Params.Retry(
          max=retries,
          allow=retries > 0,
      ),
  )
  if individual_test:
    if individual_test_name is None:
      individual_test_name = '%s-test' % request_name_tag
    return Request(
        params=params, test_plan=Request.TestPlan(test=[
            Request.Test(
                autotest=Request.Test.Autotest(name=individual_test_name))
        ]))
  if suite_name is None:
    request_suite_name = '%s-suite' % request_name_tag
  else:
    #  Prevent mangling suite name
    request_suite_name = suite_name
  return Request(
      params=params, test_plan=Request.TestPlan(
          suite=[Request.Suite(name=request_suite_name)],
          tag_criteria=tag_criteria, seed=seed, total_shards=total_shards,
          enable_autotest_sharding=enable_autotest_sharding))


# pylint: disable=dangerous-default-value
def _cft_test_request(request_name, build_target='foo-build-target',
                      individual_test=False, individual_test_name=None,
                      tag_criteria=None, seed=None,
                      software_deps=_default_software_dependencies(), retries=0,
                      total_shards=0, suite_name=None,
                      enable_autotest_sharding=False, swarming_tags=[]):
  test_req = _test_request(request_name, build_target,
                           individual_test=individual_test,
                           individual_test_name=individual_test_name,
                           tag_criteria=tag_criteria, seed=seed,
                           software_deps=software_deps, retries=retries,
                           total_shards=total_shards, suite_name=suite_name,
                           enable_autotest_sharding=enable_autotest_sharding,
                           swarming_tags=swarming_tags)
  test_req.params.run_via_cft = True
  return test_req


def _cft_test_request_without_container_metadata(tag):
  test_req = _cft_test_request(tag)
  test_req.params.metadata.container_metadata_url = ''
  return test_req


def _cft_test_request_with_build_target_in_keyvals(tag):
  test_req = _cft_test_request(tag)
  test_req.params.decorations.CopyFrom(
      Request.Params.Decorations(
          autotest_keyvals={'build_target': 'foo-build-target'}))
  return test_req


def _test_config(tag):
  return Config(
      skylab_worker=Config.SkylabWorker(luci_project='%s luci project' % tag),
  )


def _mock_container_metadata_step(api, tag, build_target='foo-build-target'):
  return api.step_data(
      'retrieve container metadata'
      '.get container metadata from GS.gsutil cat gs://{tag}-container-metadata-url'
      .format(tag=tag), stdout=api.raw_io.output(
          json.dumps({
              'containers': {
                  build_target: {
                      'images': {
                          'some-service': {
                              'digest': '123abc',
                          },
                      },
                  }
              }
          }),
      ))


def _succeeded_request_execute_response():
  tr = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='foo-passed',
      state=TaskState(verdict='VERDICT_PASSED',
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
      state=TaskState(verdict='VERDICT_FAILED',
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
      state=TaskState(verdict='VERDICT_FAILED',
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  complete_tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict='VERDICT_FAILED',
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )

  incomplete_tr_1 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict='VERDICT_FAILED',
                      life_cycle='LIFE_CYCLE_ABORTED'),
  )
  incomplete_tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict='VERDICT_FAILED',
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
      state=TaskState(verdict='VERDICT_FAILED',
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-fail',
      state=TaskState(verdict='VERDICT_FAILED',
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
      state=TaskState(verdict='VERDICT_FAILED',
                      life_cycle='LIFE_CYCLE_ABORTED'),
  )
  tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='bar-fail',
      state=TaskState(verdict='VERDICT_FAILED',
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
      state=TaskState(verdict='VERDICT_FAILED',
                      life_cycle='LIFE_CYCLE_ABORTED'),
  )
  tr_2 = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='bar-fail',
      state=TaskState(verdict='VERDICT_FAILED',
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


def _generic_cft_enumerate_response(api):
  return api.step_data(
      'enumerate CFT tests.call `cros-tool-runner`.test-finder',
      stdout=api.raw_io.output('''
{
   "test_suites":[
      {
         "test_cases":{
            "test_cases":[
               {
                  "id":{
                     "value":"foo-test"
                  },
                  "dependencies":[
                     {
                        "value":"foo-dep:bar"
                     }
                  ]
               }
            ]
         }
      }
   ]
}'''))


# Not currently used, but keeping it in a comment, as we might need to backfill
# test data.
# def _generic_cft_filter_tests_response(api):
#   return api.step_data(
#       'enumerate CFT tests.filter test cases.call `cros-tool-runner`.pre-process',
#       stdout=api.raw_io.output('''
# {
#   "response": {
#     "testSuites": [
#       {
#         "test_cases":{
#             "test_cases":[
#                {
#                   "id":{
#                      "value":"foo-test"
#                   },
#                   "dependencies":[
#                      {
#                         "value":"foo-dep:bar"
#                      }
#                   ]
#                }
#             ]
#          }
#       }
#     ],
#     "removedTests": [
#       "foo-test-removed"
#     ]
#   }
# }'''))


def _multiple_test_cases_cft_enumerate_response(api, number_of_test_cases):
  test_cases = ',\n'.join([
      '''{
      "id":{
          "value":"foo-test-%s"
      },
      "dependencies":[
          {
            "value":"foo-dep:bar"
          }
      ]
    }''' % i for i in range(number_of_test_cases)
  ])
  return api.step_data(
      'enumerate CFT tests.call `cros-tool-runner`.test-finder',
      stdout=api.raw_io.output('''
{
   "test_suites":[
      {
         "test_cases":{
            "test_cases":[
               %s
            ]
         }
      }
   ]
}''' % test_cases))


def _empty_cft_enumerate_response(api):
  return api.step_data(
      'enumerate CFT tests.call `cros-tool-runner`.test-finder',
      stdout=api.raw_io.output('{ "test_suites":[ { "test_cases":{} } ] }'))


def _generic_passing_execute_response(api):
  task_results = [
      ExecuteResponse.TaskResult(
          task_url='foo://bar/baz/b100',
          log_url='logs://bar/baz',
          name='foo-passed',
          state=TaskState(verdict='VERDICT_PASSED',
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
  def _set_build(bid=None, tags=None, experiments=None,
                 ancestor_buildbucket_ids=None):
    # tags is a dict, convert that into [StringPair].
    bb_tags = api.cros_tags.tags(**tags) if tags else []
    build_msg = api.buildbucket.ci_build_message(build_id=bid, tags=bb_tags,
                                                 experiments=experiments,
                                                 project='chromeos',
                                                 bucket='testplatform',
                                                 builder='cros_test_platform')
    if ancestor_buildbucket_ids:
      build_msg.ancestor_ids.extend(ancestor_buildbucket_ids)
    return api.buildbucket.build(build_msg)

  # Missing request and requests should cause a recipe crash
  yield api.test(
      'no-requests',
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  # Setting request should cause a recipe crash
  yield api.test(
      'has-deprecated-request',
      api.properties(
          CrosTestPlatformProperties(
              request=Request(),
              requests={'first': Request()},
          )),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  # Request with a very long timeout should cause build failure.
  yield api.test(
      'timeout-too-long',
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
              })),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'neither-priority-and-qs_account-set',
      api.properties(CrosTestPlatformProperties(requests={'first': Request()})),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  # Request with too large priority should cause build failure.
  yield api.test(
      'priority-out-of-range',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first':
                      Request(
                          params=Request.Params(
                              scheduling=Request.Params.Scheduling(
                                  priority=300)),
                      )
              })),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  # Request setting both priority and qs_account should cause build failure.
  yield api.test(
      'both-priority-and-qs_account-set',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'first':
                      Request(
                          params=Request.Params(
                              scheduling=Request.Params.Scheduling(
                                  priority=100, qs_account='foo-qs-account')),
                      )
              })),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'deprecated-managed-pool',
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
              })),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'skylab-tool-launched-build-with-invalid-service-version',
      api.properties(
          CrosTestPlatformProperties(requests={'first': Request()}), **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version_pb.ServiceVersion(skylab_tool=3)),
          }),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'skylab-tool-launched-build-with-valid-service-version',
      api.properties(
          CrosTestPlatformProperties(requests={'first': Request()}), **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version_pb.ServiceVersion(skylab_tool=4)),
          }),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'Duplicate-software-dependencies',
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
                                      chromeos_build='duplicate-build',
                                  ),
                                  Request.Params.SoftwareDependency(
                                      chromeos_build='duplicate-build',
                                  ),
                                  Request.Params.SoftwareDependency(
                                      ro_firmware_build='single-ro-firmware',
                                  ),
                                  Request.Params.SoftwareDependency(
                                      rw_firmware_build='duplicate-rw-firmware',
                                  ),
                                  Request.Params.SoftwareDependency(
                                      rw_firmware_build='duplicate-rw-firmware-diff-value',
                                  ),
                              ],
                          ),
                      )
              },
          ),
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  # Config set the result flow pubsub project and topic should push build ID.
  yield api.test(
      'Config-has-pubsub-topic-to-publish-CTP-build-ID',
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
                  publish.PublishResponse(state=common.SUCCEEDED)))),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  # Recipe running on the top level build without parent build ID.
  yield api.test(
      'Recipe-runs-on-top-level-build-without-parent-build-id',
      _set_build(bid=42),
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
                  publish.PublishResponse(state=common.SUCCEEDED)))),
      _generic_enumerate_response(api),
      _generic_passing_execute_response(api),
      api.post_process(post_process.StepSuccess,
                       'configure resultdb bigquery export'),
      api.post_process(
          post_process.StepSuccess,
          'configure resultdb bigquery export.mark resultdb invocation for bigquery export'
      ),
  )

  # Recipe running on the child build with ancestor build ids. ResultDB BigQuery
  # export is skipped.
  yield api.test(
      'Recipe-runs-on-child-build-with-ancestor-ids',
      _set_build(bid=42, ancestor_buildbucket_ids=[123, 456]),
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
                  publish.PublishResponse(state=common.SUCCEEDED)))),
      _generic_enumerate_response(api),
      _generic_passing_execute_response(api),
      api.post_process(post_process.DoesNotRun,
                       'configure resultdb bigquery export'),
  )

  yield api.test(
      'Recipe-runs-on-child-build-with-ancestor-ids-force-export',
      _set_build(bid=42, ancestor_buildbucket_ids=[123, 456]),
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _test_request('default')},
              config=Config(
                  pubsub=Config.PubSub(project='foo-proj', topic='foo-topic')),
              force_export=True,
          )),
      api.step_data(
          'publish build ID.call `result_flow`.publish',
          stdout=api.raw_io.output(
              json_format.MessageToJson(
                  publish.PublishResponse(state=common.SUCCEEDED)))),
      _generic_enumerate_response(api),
      _generic_passing_execute_response(api),
      api.post_process(post_process.MustRun,
                       'configure resultdb bigquery export'),
      api.post_process(post_process.DropExpectation),
  )

  # Recipe running outside Buildbucket should skip publishing build ID.
  yield api.test(
      'Recipe-runs-without-Build-ID', _set_build(bid=0),
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _test_request('default')},
              config=Config(
                  pubsub=Config.PubSub(project='foo-proj', topic='foo-topic')),
          )), _generic_enumerate_response(api),
      _generic_passing_execute_response(api))

  # Config missing result flow topic name should skip publishing build ID.
  yield api.test(
      'Recipe-runs-without-result-flow-pubsub-topic',
      _set_build(bid=8874582904031090640),
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _test_request('default')},
              config=Config(pubsub=Config.PubSub(project='foo-proj')))),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  # Config missing result flow project name should skip publishing build ID.
  yield api.test(
      'Recipe-runs-without-result-flow-pubsub-project',
      _set_build(bid=8874582904031090640),
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _test_request('default')},
              config=Config(pubsub=Config.PubSub(topic='foo-topic')))),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  # An end-to-end run with ctp release version tagging.
  yield api.test(
      'end-to-end-skylab-execution-with-ctp-release-version-tagging',
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
      'end-to-end-skylab-execution-with-no-ctp-release-version-found',
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

  # An end-to-end run with partner_config set to skip cros_test_postprocess
  yield api.test(
      'end-to-end-execution-with-passed-tasks-with-partner-config',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'),
                                     partner_config=True)),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  # An end-to-end CQ retry run.
  yield api.test(
      'end-to-end-execution-cq-retry',
      _generic_enumerate_response(api),
      _generic_passing_execute_response(api),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.cros_history.is_retry(True),
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      api.post_check(post_process.PropertyEquals, 'is_retry', True),
      api.post_process(post_process.DropExpectation),
  )

  # An end-to-end CQ first attempt.
  yield api.test(
      'end-to-end-execution-cq-first-attempt',
      _generic_enumerate_response(api),
      _generic_passing_execute_response(api),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      api.post_check(post_process.PropertyEquals, 'is_retry', False),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'end-to-end-execution-with-passed-tasks',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  yield api.test(
      'end-to-end-execution-with-passed-tasks-with-suite-limit-experiment',
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _test_request('foo')},
              config=_test_config('foo'),
              experiments=[CrosTestPlatformProperties.SUITE_EXECUTION_LIMIT])),
      _generic_enumerate_response(api), _generic_passing_execute_response(api))

  passed_task_result = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='foo-passed',
      state=TaskState(verdict='VERDICT_PASSED',
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  skipped_task_result = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b101',
      log_url='logs://bar/baz1',
      name='foo-skipped',
      state=TaskState(verdict='VERDICT_NO_VERDICT',
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  yield api.test(
      'end-to-end-execution-with-passed-and-skipped-tasks',
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
      'end-to-end-execution-with-empty-response',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      _generic_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(tagged_responses={}),
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  failed_task_results = [
      ExecuteResponse.TaskResult(
          task_url='foo://bar/baz/b100',
          log_url='logs://bar/baz',
          name='foo-failed',
          state=TaskState(verdict='VERDICT_FAILED',
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
          state=TaskState(verdict='VERDICT_FAILED',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
          test_cases=[
              ExecuteResponse.TaskResult.TestCaseResult(
                  name='failed-test-case', verdict=TaskState.VERDICT_FAILED)
          ],
      ),
  ]
  yield api.test(
      'end-to-end-execution-with-failed-tasks',
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
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  retried_task_results = [
      ExecuteResponse.TaskResult(
          task_url='foo://foo/foo/0',
          log_url='logs://foo/foo',
          name='foo-test',
          state=TaskState(verdict='VERDICT_FAILED',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='foo://foo/foo/1',
          log_url='logs://foo/foo1',
          name='foo-test',
          attempt=1,
          state=TaskState(verdict='VERDICT_PASSED',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='bar://bar/bar/0',
          log_url='logs://bar/bar',
          name='bar-test',
          state=TaskState(verdict='VERDICT_NO_VERDICT',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='bar://bar/bar/1',
          log_url='logs://bar/bar1',
          name='bar-test',
          attempt=1,
          state=TaskState(verdict='VERDICT_PASSED',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='baz://baz/baz/0',
          log_url='logs://baz/baz',
          name='baz-test',
          state=TaskState(life_cycle='LIFE_CYCLE_REJECTED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='baz://baz/baz/1',
          log_url='logs://baz/baz1',
          name='baz-test',
          attempt=1,
          state=TaskState(verdict='VERDICT_PASSED',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='haha://haha/haha/0',
          log_url='logs://haha/haha',
          name='haha-test',
          state=TaskState(life_cycle='LIFE_CYCLE_CANCELLED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='haha://haha/haha/1',
          log_url='logs://haha/haha1',
          name='haha-test',
          attempt=1,
          state=TaskState(verdict='VERDICT_PASSED',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='lol://lol/lol/0',
          log_url='logs://lol/lol',
          name='lol-test',
          state=TaskState(life_cycle='LIFE_CYCLE_ABORTED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='lol://lol/lol/1',
          log_url='logs://lol/lol1',
          name='lol-test',
          attempt=1,
          state=TaskState(verdict='VERDICT_PASSED',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
      ExecuteResponse.TaskResult(
          task_url='lmao://lmao/lmao/0',
          log_url='logs://lmao/lmao',
          name='lmao-test',
          state=TaskState(life_cycle='LIFE_CYCLE_PENDING'),
      ),
      ExecuteResponse.TaskResult(
          task_url='lmao://lmao/lmao/1',
          log_url='logs://lmao/lmao1',
          name='lmao-test',
          attempt=1,
          state=TaskState(verdict='VERDICT_PASSED',
                          life_cycle='LIFE_CYCLE_COMPLETED'),
      ),
  ]
  yield api.test(
      'end-to-end-execution-with-failed-then-passed-tasks',
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
      state=TaskState(life_cycle='LIFE_CYCLE_REJECTED'),
  )
  task_result_foo = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100', log_url='logs://bar/baz', name='foo',
      state=TaskState(life_cycle='LIFE_CYCLE_REJECTED'), rejected_dimensions=[
          ExecuteResponse.TaskResult.RejectedTaskDimension(
              key='dim1', value='val1'),
          ExecuteResponse.TaskResult.RejectedTaskDimension(
              key='dim2', value='val2'),
      ])
  yield api.test(
      'end-to-end-execution-with-rejected-tasks',
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
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  pending_task_result = ExecuteResponse.TaskResult(
      task_url=None,
      log_url=None,
      name='foo-pending',
      state=TaskState(life_cycle='LIFE_CYCLE_PENDING'),
  )
  yield api.test(
      'end-to-end-execution-with-pending-tasks',
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
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  task_results = [
      ExecuteResponse.TaskResult(
          task_url=None,
          log_url=None,
          name='foo-cancelled',
          state=TaskState(life_cycle='LIFE_CYCLE_CANCELLED'),
      ),
  ]
  yield api.test(
      'end-to-end-execution-with-cancelled-tasks',
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
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  aborted_task_result = ExecuteResponse.TaskResult(
      task_url=None,
      log_url=None,
      name='foo-aborted',
      state=TaskState(life_cycle='LIFE_CYCLE_ABORTED'),
  )
  yield api.test(
      'end-to-end-execution-with-aborted-tasks',
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
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'empty-enumeration',
      api.properties(
          CrosTestPlatformProperties(requests={'first': _test_request('foo')},
                                     config=_test_config('foo'))),
      _empty_enumerate_response(api),
      status='FAILURE',
  )

  yield api.test(
      'enumeration-error',
      api.properties(
          CrosTestPlatformProperties(requests={'default': _test_request('foo')},
                                     config=_test_config('foo'))),
      api.cros_test_platform.set_enumerate_response_json(
          'enumerate tests',
          '''
  {
    "tagged_responses": {
      "default": {
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
                                          verdict='VERDICT_FAILED'))
              }),
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  task_result_foo = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='foo-failed',
      state=TaskState(verdict='VERDICT_FAILED',
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  task_result_baz = ExecuteResponse.TaskResult(
      task_url='foo://bar/baz/b100',
      log_url='logs://bar/baz',
      name='baz-failed',
      state=TaskState(verdict='VERDICT_FAILED',
                      life_cycle='LIFE_CYCLE_COMPLETED'),
  )
  yield api.test(
      'execution-with-two-failed-invocations',
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
                          ], consolidated_results=[
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=[task_result_foo])
                          ]),
                  'second':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_FAILED'),
                          task_results=[
                              task_result_baz,
                          ], consolidated_results=[
                              ExecuteResponse.ConsolidatedResult(
                                  attempts=[task_result_baz])
                          ]),
              }),
      ),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'end-to-end-multi-requests',
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
          len(GetBuildProperties(steps).get('compressed_responses', {})) > 0)),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'cft-suite-with-tags-execution-with-passed-tasks',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']),
                          total_shards=5)
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cft-translate-to-v2',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']),
                          total_shards=5,
                          swarming_tags=['label-pool:schedukeTest'])
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
  )

  yield api.test(
      'cq-cft-suite-with-filtered-tests-with-passed-tasks',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']),
                          total_shards=5)
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cq-cft-suite-with-unfiltered-tests-with-passed-tasks',
      api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']),
                          total_shards=5)
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cft-suite-with-tags-with-multiple-tests-with-passed-tasks',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']))
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _multiple_test_cases_cft_enumerate_response(api, 101),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cft-suite-with-tags-but-no-tests-with-passed-tasks',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']))
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _multiple_test_cases_cft_enumerate_response(api, 0),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cft-suite-without-tags-execution-with-passed-tasks',
      api.properties(
          CrosTestPlatformProperties(
              requests={'default': _cft_test_request('foo')},
              config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cft-suite-without-tags-execution-with-passed-tasks-enabled-autotest-sharding',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request('foo', enable_autotest_sharding=True)
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cft-individual-test-execution-with-passed-tasks',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default': _cft_test_request('foo', individual_test=True)
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cft-individual-test-execution-with-keyval-build_target-with-passed-tasks',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request_with_build_target_in_keyvals('foo')
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cft-suite-mixed-with-non-cft-suite',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'cft':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop'])),
                  'default':
                      _test_request('default')
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _generic_enumerate_response(api),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'cft-empty-enumeration',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']))
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _empty_cft_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_FAILED'))
              }),
      ),
      status='FAILURE',
  )

  yield api.test(
      'cft-test-execution-with-missing-container-metadata',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default': _cft_test_request_without_container_metadata('foo')
              }, config=_test_config('foo'))),
      status='FAILURE',
  )

  yield api.test(
      'suite-scheduler-lacross-retries',
      _set_build(bid=42, tags={'user_agent': 'crosfleet'}),
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', individual_test=True,
                          individual_test_name='tast.lacros',
                          tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']),
                          retries=1)
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _empty_cft_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_FAILED'))
              }),
      ),
      status='FAILURE',
  )

  yield api.test(
      'suite-scheduler-user-agents-retain-non-critical-retries',
      _set_build(bid=42, tags={'user_agent': 'suite_scheduler'}),
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']),
                          retries=1)
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _empty_cft_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_FAILED'))
              }),
      ),
      status='FAILURE',
  )

  yield api.test(
      'non-suite-scheduler-user-agents-does-not-retain-non-critical-retries',
      _set_build(bid=42, tags={'user_agent': 'example_agent'}),
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'foo', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']),
                          retries=1)
              }, config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'foo'),
      _empty_cft_enumerate_response(api),
      api.cros_test_platform.set_execute_luciexe_response(
          'execute',
          ExecuteResponses(
              tagged_responses={
                  'default':
                      ExecuteResponse(
                          state=TaskState(life_cycle='LIFE_CYCLE_COMPLETED',
                                          verdict='VERDICT_FAILED'))
              }),
      ),
      status='FAILURE',
  )

  yield api.test(
      'cft-test-execution-with-failed-metadata-reading-but-forgiven',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default': _test_request('foo'),
                  'cft-default': _cft_test_request('foo')
              }, config=_test_config('foo'))),
      api.step_data(
          'retrieve container metadata'
          '.get container metadata from GS.gsutil cat gs://{tag}-container-metadata-url'
          .format(tag='foo'),
          retcode=1,
      ),
      _generic_enumerate_response(api),
      _generic_passing_execute_response(api),
      status='FAILURE',
  )

  yield api.test(
      'cft-test-execution-with-failed-metadata-reading-and-cft-is-turned-off',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _test_request('foo'),
                  'cft-default':
                      _cft_test_request(
                          request_name='foo',
                          software_deps=_software_dependencies_with_milestone_before_108(
                          ))
              }, config=_test_config('foo'))),
      api.step_data(
          'retrieve container metadata'
          '.get container metadata from GS.gsutil cat gs://{tag}-container-metadata-url'
          .format(tag='foo'),
          retcode=1,
      ),
      status='FAILURE',
  )

  yield api.test(
      'cft-test-execution-with-no-valid-container-metadata-for-build-target',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default': _test_request('foo'),
                  'cft-default': _cft_test_request('foo', 'build_target123')
              }, config=_test_config('foo'))),
      _mock_container_metadata_step(api, 'foo', 'mismatched_build_target'),
      _generic_enumerate_response(api),
      _generic_passing_execute_response(api),
      status='FAILURE',
  )

  yield api.test(
      'cft-test-execution-with-no-valid-container-metadata-for-build-target-request-only',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'cft-default': _cft_test_request('foo', 'build_target123')
              }, config=_test_config('foo'))),
      _mock_container_metadata_step(api, 'foo', 'mismatched_build_target'),
      status='FAILURE',
  )

  yield api.test(
      'test-different-bucket',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _test_request(
                          'foo',
                          software_deps=_different_bucket_software_deps('foo')),
              }, config=_test_config('foo'))),
      _generic_enumerate_response(api),
      _generic_passing_execute_response(api),
      status='SUCCESS',
  )

  yield api.test(
      'test-different-bucket-stage-fails',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _test_request(
                          'foo',
                          software_deps=_different_bucket_software_deps('foo')),
              }, config=_test_config('foo'))),
      api.step_data(
          'staging requested build(s).staging brya-release/R108-33333.222.111.stage build request',
          retcode=22),
      _generic_enumerate_response(api),
      _generic_passing_execute_response(api),
      # Even if staging build fails, we still expect rest of recipe to function as expected.
      status='SUCCESS',
  )

  yield api.test(
      'end-to-end-execution-with-passed-tasks-with-optimization',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'bvt-tast-cq', tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']),
                          total_shards=5, suite_name='bvt-tast-cq')
              }, experiments=[CrosTestPlatformProperties.OPTIMIZED_SHARDING],
              config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'bvt-tast-cq'),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )

  yield api.test(
      'with-optimization-bvt-tast-cq-security',
      api.properties(
          CrosTestPlatformProperties(
              requests={
                  'default':
                      _cft_test_request(
                          'bvt-tast-cq-security',
                          tag_criteria=ctr_test_suite.TestSuite
                          .TestCaseTagCriteria(tags=['beep', 'boop'],
                                               tag_excludes=['blap', 'blop']),
                          total_shards=5, suite_name='bvt-tast-cq-security')
              }, experiments=[CrosTestPlatformProperties.OPTIMIZED_SHARDING],
              config=_test_config('foo')), **{
                  '$chromeos/cros_tool_runner':
                      CrosToolRunnerProperties(
                          version=CrosToolRunnerProperties.Version(
                              cipd_label='prod')),
              }),
      _mock_container_metadata_step(api, 'bvt-tast-cq-security'),
      _generic_cft_enumerate_response(api),
      _generic_passing_execute_response(api),
  )
