# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for reporting and parsing Tast VM test results."""

import datetime
from typing import List

from google.protobuf import json_format as jsonpb
from recipe_engine import recipe_api
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.request import Request as TestPlatformRequest
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState
from PB.tast.test_result import TestResult

GS_URI_PREFIX = 'gs://'
PANTHEON_PREFIX = 'https://pantheon.corp.google.com/storage/browser'
STAINLESS_LOG_PREFIX = 'https://stainless.corp.google.com/browse/'
TESTHAUS_LOG_PREFIX = 'https://tests.chromeos.goog/p/chromeos/logs/browse/'
MILO_PREFIX = 'https://ci.chromium.org/b/'
MISSING_TEST_FAILURE_SUMMARY = 'Test did not run'
FAILURE_VERDICTS = [TaskState.VERDICT_FAILED, TaskState.VERDICT_UNSPECIFIED]
SOURCES_FILE_NAME = 'sources.jsonpb'
TAST_TEST_NAME_PREFIX = 'tast.'


class TastResultsApi(recipe_api.RecipeApi):
  """A module to process tast-results/ directory."""

  def __init__(self, props, *args, **kwargs):
    """Initialize TastResultsApi."""
    super().__init__(*args, **kwargs)
    self._archive_gs_bucket = props.archive_gs_bucket or 'chromeos-vmtest-archive'

  def _get_upload_uri(self, tag):
    """Get the upload URI to Google Storage,
    e.g. gs://chromeos-vmtest-archive/reven-vmtest-direct-tast-vm/8795220244064871793/first_results

    Args:
      tag (str): Tag for this execution. Used to distinguish archive folders.

    Returns:
      upload_uri (str): link to the GCS bucket path.
    """
    build = self.m.buildbucket.build
    return 'gs://%s/%s/%s/%s' % (self._archive_gs_bucket, build.builder.builder,
                                 build.id, tag)

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=1),
                     condition=lambda e: getattr(e, 'had_timeout', False))
  def archive_dir(self, dir_path, tag):
    """Archive dir to Google Storage.

    Args:
      dir_path (Path): Path to dir to be uploaded.
      tag (str): Tag for this execution. Used to distinguish archive folders.

    Returns:
      str, link to the archive on pantheon.
    """
    with self.m.step.nest('GS upload ' + tag) as presentation:
      upload_uri = self._get_upload_uri(tag)
      self.m.gsutil(['rsync', '-r', dir_path, upload_uri], parallel_upload=True,
                    multithreaded=True,
                    timeout=self.test_api.gsutil_timeout_seconds)

      build = self.m.buildbucket.build
      pantheon_url = '%s/%s/%s/%s/%s' % (PANTHEON_PREFIX,
                                         self._archive_gs_bucket,
                                         build.builder.builder, build.id, tag)
      presentation.links['archive_link'] = pantheon_url
      return pantheon_url

  def get_results(self, test_results_path, suite_name, tag, tests,
                  build_artifacts_url=None, new_invocation=False):
    """Return the test results decoded from the streamed_results.jsonl.

    Args:
      test_results_path (Path): Path to test_results/.
      suite_name (str): Name of the whole test suite.
      tag (str): Tag for this execution. Used to distinguish archive folders.
      tests list(str): List of tests that should have been executed.
      build_artifacts_url (str): GS Link to the artifacts of the build.
          Ex: 'gs://chromeos-image-archive/betty-cq/R111-2349872/'
      new_invocation (bool): Whether the test results should be uploaded in a
          new invocation.

    Returns:
      A consolidated Data Structure summarizing all results from a run.
      Currently this is a TaskResult.
      https://crrev.com/ee30a869473a8ee54246e0469ede2aa010fb2e48/src/test_platform/steps/execution.proto#47
    """
    with self.m.step.nest('process tast output') as pres:
      if not tests:
        pres.step_text = 'no tests ran'
        return ExecuteResponse.TaskResult(
            name=suite_name,
            state=TaskState(verdict=TaskState.VERDICT_PASSED,
                            life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
            log_url=None, attempt=0, test_cases=[])

      test_results = self._read_results_json(test_results_path)
      test_cases = [self.convert_to_testcaseresult(r) for r in test_results]
      reported_tests = {tc.name for tc in test_cases}
      missing_test_names = [
          test for test in tests if test not in reported_tests
      ]

      self.upload_to_resultdb(test_results_path, suite_name, missing_test_names,
                              tag, build_artifacts_url,
                              new_invocation=new_invocation)

      # If even one test failed, the suite should report failure.
      all_verdicts = [t.verdict for t in test_cases]
      overall_state = TaskState(verdict=TaskState.VERDICT_PASSED,
                                life_cycle=TaskState.LIFE_CYCLE_COMPLETED)
      log_url = self.archive_dir(test_results_path, tag + '_results')

      if len(test_cases) < len(tests):  #pragma: nocover
        overall_state.verdict = TaskState.VERDICT_FAILED
        test_cases += self.create_missing_test_results(missing_test_names)
      elif TaskState.VERDICT_FAILED in all_verdicts:
        overall_state.verdict = TaskState.VERDICT_FAILED
      return ExecuteResponse.TaskResult(name=suite_name, state=overall_state,
                                        log_url=log_url, attempt=0,
                                        test_cases=test_cases)

  def _read_results_json(self, test_results_path):
    """Read the streamed_results.jsonl file and return structured contents.

    Args:
      test_results_path (Path): Path to test_results/.

    Returns:
      list(TestResult).
      https://crrev.com/62d6530f6f61417cf47a2bcea8bb714470ef5ca2/src/tast/test_result.proto
    """
    list_of_results = []
    try:
      list_of_results = self.m.file.read_text(
          'read streamed_results.jsonl',
          test_results_path.join('streamed_results.jsonl'),
          test_data=self.test_api.test_streamed_results_jsonl).splitlines()
      # Handle empty streamed_results.jsonl file.
      list_of_results = [self.m.json.loads(x) for x in list_of_results or []]
    except self.m.file.Error:  # pragma: nocover
      # Carry on if streamed_results.jsonl doesn't exist.
      pass
    return [
        jsonpb.ParseDict(result, TestResult(), ignore_unknown_fields=True)
        for result in list_of_results
    ]

  def create_missing_test_results(self, missing_test_names):
    """Create test results for the missing test cases.

    Args:
      missing_test_names list(str): Tests that should have run but didn't.

    Returns:
      list(TestCaseResult) Test results for the missing tests cases.
    """
    return [
        ExecuteResponse.TaskResult.TestCaseResult(
            name=test, verdict=TaskState.VERDICT_FAILED,
            human_readable_summary=MISSING_TEST_FAILURE_SUMMARY)
        for test in missing_test_names
    ]

  def convert_to_testcaseresult(self, test_result):
    """Convert Tast's result into CTP format.

    Args:
      test_result (TestResult): TestResult to be converted.

    Returns:
      TestCaseResult with the same info.
    """
    task_summary = ''
    if test_result.skip_reason:
      verdict = TaskState.VERDICT_NO_VERDICT
      task_summary = test_result.skip_reason
    elif not test_result.errors:
      verdict = TaskState.VERDICT_PASSED
    else:
      verdict = TaskState.VERDICT_FAILED
      task_summary = ', '.join([e.reason for e in test_result.errors])

    return ExecuteResponse.TaskResult.TestCaseResult(
        name=test_result.name,
        verdict=verdict,
        human_readable_summary=task_summary,
    )

  def convert_results(self, task_result, exclude_tests=None):
    """Convert TaskResult into api.failures.Results object and dicts.

    Args:
      task_result (TaskResult): TaskResult to be converted.
      exclude_tests list(str): List of names of tests to be
        excluded.

    Returns:
      A tuple of api.failures.Results object and list(dict) representing
      failed test cases excluding the ones provided.
    """
    kind = 'vm test'
    results = self.m.failures.Results(failures=[], successes={kind: 0})
    failed_test_cases = []
    build = self.m.buildbucket.build

    exclude_tests = exclude_tests or []
    for test_case in task_result.test_cases:
      if test_case.name not in exclude_tests:
        if test_case.verdict == TaskState.VERDICT_FAILED:
          results.failures.append(
              self.m.failures.Failure(
                  kind=kind,
                  title=test_case.name,
                  link_map={
                      test_case.human_readable_summary[:50]:
                          ('%s%d/test-results?q=ID%%3A%s' %
                           (MILO_PREFIX, build.id, test_case.name))
                  },
                  fatal=True,
                  id=None,
              ))
          failed_test_cases.append(jsonpb.MessageToDict(test_case))
        else:
          results.successes[kind] += 1

    return results, failed_test_cases

  def print_results(self, failures, empty_result):
    """Print results for the user.

    Args:
      failures(list(Failure)): Failures of this run.
      empty_result(bool): Were the results empty?
    """
    with self.m.step.nest('print results') as presentation:
      if not failures:
        presentation.step_text = 'all tests passed!'
      else:
        presentation.status = self.m.step.FAILURE
        for failure in failures:
          with self.m.step.nest(failure.title) as test_presentation:
            test_presentation.status = self.m.step.FAILURE
            for text, log in failure.link_map.items():
              test_presentation.links['logs'] = log
              test_presentation.step_text = text

      if empty_result:
        presentation.status = self.m.step.EXCEPTION
        presentation.step_text = 'empty result'
        # Ensure the recipe fails as well.
        raise self.m.step.InfraFailure('No results dumped; Likely a tast crash')

  def record_logs(self, sys_log_dir):
    """Print system logs to MILO.

    Args:
      sys_log_dir(str): absolute dir path to copy logs from.
    """
    with self.m.step.nest('record logs') as presentation:
      dump_dir = self.m.path.mkdtemp('var-log-dump')
      self.m.step('copy logs',
                  ['sudo', '-n', 'cp', '-rf', sys_log_dir,
                   str(dump_dir)])
      self.m.step('loosen permission',
                  ['sudo', '-n', 'chmod', '-R', '777',
                   str(dump_dir)])
      archive_link = self.archive_dir(dump_dir, 'system_logs')
      presentation.links['system_logs'] = archive_link

  def _match_to_testscenario(self, test_case, scenario):
    return (test_case.name == scenario.test_name and
            test_case.verdict == scenario.verdict and
            scenario.reason in test_case.human_readable_summary)

  def _match_to_reasonscenario(self, test_case, scenario):
    return (test_case.verdict == scenario.verdict and
            scenario.reason in test_case.human_readable_summary)

  def get_tests_to_retry(self, task_result):
    """Determine which tests to retry.

    Args:
      task_result(TaskResult): TaskResult of the test suite.

    Returns:
      list(str) names of tests to be retried and a boolean that
      requires VM restart before retry.
    """
    with self.m.step.nest('tests to retry') as presentation:
      if task_result.state.verdict == TaskState.VERDICT_PASSED:
        presentation.step_text = 'All tests passed!'
        return [], False

      test_map = {
          t.name: t
          for t in task_result.test_cases
          if t.verdict in FAILURE_VERDICTS
      }
      tests_to_retry = []
      step_log = []
      retry_config = self.m.cros_infra_config.get_vm_retry_config()
      presentation.logs['retry_config'] = str(retry_config)
      presentation.logs['failed_tests'] = str(test_map)
      requires_restart = False
      for scenario in retry_config.reason_scenarios:
        for name, test in test_map.items():
          if self._match_to_reasonscenario(test, scenario):
            step_log.append('Found match {}<->{}'.format(test, scenario))
            tests_to_retry.append(name)
            requires_restart |= scenario.requires_restart

      for scenario in retry_config.suite_scenarios:
        if scenario.test_name in test_map:
          failed_test = test_map[scenario.test_name]
          if self._match_to_testscenario(failed_test, scenario):
            step_log.append('Found match {}<->{}'.format(failed_test, scenario))
            tests_to_retry.append(scenario.test_name)
            requires_restart |= scenario.requires_restart
            continue

      presentation.logs['matches'] = step_log
      # Make the tests list unique.
      tests_to_retry = list(set(tests_to_retry))
      return tests_to_retry, requires_restart

  def _convert_to_task_request_id(self, swarming_task_run_id):
    """ Returns the swarming task request id.

    Args:
      swarming_task_run_id: The swarming task run id.

    Returns:
      swarming_task_request_id (string): The swarming task request id.
    """
    if not swarming_task_run_id:
      return ''

    # Converts the swarming task run id with non "0" suffix to the swarming task
    # request id with "0" suffix. Both can be used to point to the same swarming
    # task. Swarming supported implicit retry and first task has "1" in suffix
    # and retried task has "2" in suffix.
    return swarming_task_run_id[:-1] + '0'

  def _generate_resultdb_base_tags(self, tag, suite_name):
    """Generate the base tags for the test results.

    This function adds the following tags:
      * hostname: Default to "vm".
      * board: The same as build target,
          e.g. reven-vmtest
      * model: The same as build target,
          e.g. reven-vmtest
      * logs_url: URL for test result logs,
          e.g. gs://chromeos-vmtest-archive/reven-vmtest-direct-tast-vm/8795220244064871793/first_results
      * suite_task_id: The parent's swarming task ID,
          e.g. 59ef5e9532bbd611
      * task_id: The swarming task ID,
          e.g. 59f0e13fe7af0710
      * job_name: The swarming task name (swarming request name),
          e.g. bb-8802802052277719089-chromeos/vmtest/amd64-generic-direct-tast-vm
      * queued_time:
          e.g. "2022-06-03 00:15:34.000000 UTC".
      * ancestor_buildbucket_ids: All the ancestor buildbucket ids,
          e.g. "8814950840874708945, 8814951792758733697"
      * image:
          e.g. novato-postsubmit/R111-15302.0.0-76073-8792941570274926657
      * build:
          e.g. R111-15302.0.0-76073-8792941570274926657
      * pool: Device pool, an optional dimension to Swarming, which is used only
          by ChromeOS,
          e.g. "ChromeOSSkylab"
      * kernel_version:
          e.g. "5.4.151-16902-g93699f4e73de"
      * builder_name: build config name,
          e.g. reven-vmtest-cq
      * buildbucket_builder: buildbucket builder name,
          e.g. "test runner"

    Args:
      tag (str): Tag for this execution. Used to distinguish archive folders.
      suite_name (str): Name of the whole test suite.
    Returns:
      base_tags (list[tuples]): Tags for the test results.
    """
    base_tags = []
    base_tags.append(('hostname', 'vm'))

    build_target = self.m.cros_infra_config.get_build_target_name()
    if build_target:
      base_tags.append(('board', build_target))
      base_tags.append(('model', build_target))

    logs_url = self._get_upload_uri(tag + '_results')
    if logs_url:
      base_tags.append(('logs_url', logs_url))

    # Fetches the following information from swarming api.
    base_tags.append(
        ('task_id', self._convert_to_task_request_id(self.m.swarming.task_id)))

    # Fetches the following information from buildbucket.build.
    build = self.m.buildbucket.build
    builder_object = build.builder
    build_id = str(build.id)
    job_name = 'bb-{}-{}/{}/{}'.format(build_id, builder_object.project,
                                       builder_object.bucket,
                                       builder_object.builder)
    base_tags.append(('job_name', job_name))
    base_tags.append(('buildbucket_builder', builder_object.builder))

    queued_time = datetime.datetime.utcfromtimestamp(build.create_time.seconds)
    base_tags.append(
        ('queued_time', queued_time.strftime('%Y-%m-%d %H:%M:%S.%f UTC')))

    ancestor_buildbucket_ids = ','.join(str(id) for id in build.ancestor_ids)
    if ancestor_buildbucket_ids:
      base_tags.append(('ancestor_buildbucket_ids', ancestor_buildbucket_ids))

    # Fetches build config from "artifactsGsPath" input property first and then
    # fallback to the suite if required.
    builder_name = None
    if 'buildPayload' in build.input.properties \
      and 'artifactsGsPath' in build.input.properties['buildPayload']:
      image = build.input.properties['buildPayload']['artifactsGsPath']
      if image:
        builder_name = image.split('/')[0]
    if not builder_name:
      builder_name = suite_name.split('.')[0] if suite_name else None
    if builder_name:
      base_tags.append(('builder_name', builder_name))

    # Fetches the following information from buildbucket.build.infra.swarming.
    suite_task_id = self._convert_to_task_request_id(
        build.infra.swarming.parent_run_id)
    if suite_task_id:
      base_tags.append(('suite_task_id', suite_task_id))

    # Fetches the following information from buildbucket.build.input.properties.
    if 'buildPayload' in build.input.properties \
      and 'artifactsGsPath' in build.input.properties['buildPayload']:
      image = build.input.properties['buildPayload']['artifactsGsPath']
      if image:
        base_tags.append(('image', image))
        base_tags.append(('build', image.split('/')[-1]))

    # Fetches the following information from buildbucket.swarming bot
    # dimensions.
    bot_dimensions = build.infra.swarming.bot_dimensions
    pool = self.m.cros_tags.get_values('pool', bot_dimensions)
    if pool:
      base_tags.append(('pool', pool[0]))

    kernel_version = self.m.cros_tags.get_values('kernel', bot_dimensions)
    if kernel_version:
      base_tags.append(('kernel_version', kernel_version[0]))

    return base_tags

  def _generate_resultdb_variant_def(self):
    """Generate the variant defintions for the test results.

    This function adds the following tags:
      * build_target:
          e.g. reven-vmtest

    Returns:
      base_variant (dict): Variant attributes for the test results.
    """
    base_variant = {}

    build_target = self.m.cros_infra_config.get_build_target_name()
    if build_target:
      base_variant['build_target'] = build_target
    return base_variant

  def _generate_resultdb_sources_file(self, build_artifacts_url):
    """Download the source metadata file and return the path to it."""
    # Source information is stored with the build, at
    # /metadata/sources.jsonpb.
    sources_url = self.m.path.join(build_artifacts_url, 'metadata',
                                   SOURCES_FILE_NAME)
    sources_local_path = self.m.path.mkdtemp(
        prefix='source_metadata').join(SOURCES_FILE_NAME)
    try:
      # Download the file from Google Stroage.
      self.m.gsutil.download_url(sources_url, sources_local_path,
                                 name='download metadata/sources.jsonpb')
    except self.m.step.StepFailure:
      return ''
    return str(sources_local_path)

  def upload_to_resultdb(self, test_results_path, suite_name,
                         missing_test_names, tag, build_artifacts_url=None,
                         new_invocation=False):
    """Upload the test results to ResultDB.

    Args:
      test_results_path (Path): Path to test_results.
      suite_name (str): Name of the whole test suite.
      missing_test_names: Test results for the missing tests cases.
      tag (str): Tag for this execution. Used to distinguish archive folders.
      build_artifacts_url (str): GS Link to the artifacts of the build.
          Ex: 'gs://chromeos-image-archive/betty-cq/R111-2349872/'
    """
    if not self.m.resultdb.enabled:
      return

    config = {
        'result_format': 'tast',
        'result_file': test_results_path.join('streamed_results.jsonl'),
        'artifact_directory': self.m.path.abspath(test_results_path),
        'base_variant': self._generate_resultdb_variant_def(),
        'base_tags': self._generate_resultdb_base_tags(tag, suite_name),
        'include': new_invocation,
    }
    if build_artifacts_url:
      sources_file = self._generate_resultdb_sources_file(build_artifacts_url)
      if sources_file:
        config['sources_file'] = sources_file

    gs_bucket_path = self._get_upload_uri(tag +
                                          '_results').split(GS_URI_PREFIX)[-1]

    # TODO: Replace the GS bucket path with invocation id once Testhaus adapts
    # a new log URL format.
    testhaus_log_url = TESTHAUS_LOG_PREFIX + gs_bucket_path
    self.m.cros_resultdb.upload(config, testhaus_log_url)

    missing_test_names_with_prefix = []
    for test_name in missing_test_names:
      prefix = '' if test_name.startswith(
          TAST_TEST_NAME_PREFIX) else TAST_TEST_NAME_PREFIX
      missing_test_names_with_prefix.append(f'{prefix}{test_name}')

    self.m.cros_resultdb.report_missing_test_cases(
        missing_test_names_with_prefix, config.get('base_variant'),
        config.get('base_tags'))
    if not self.m.buildbucket.is_critical():
      behavior = TestPlatformRequest.Params.TestExecutionBehavior.NON_CRITICAL
      self.m.cros_resultdb.apply_exonerations(
          [self.m.cros_resultdb.current_invocation_id], behavior)

  def extract_failed_test_names(self, vm_test_build: Build) -> List[str]:
    """Returns the failed test names from the output properties of the build."""
    props = jsonpb.MessageToDict(vm_test_build.output.properties)
    failed_test_cases = props.get('failed_test_cases', [])
    failed_test_names = [test_case['name'] for test_case in failed_test_cases]
    return failed_test_names

  def had_no_unexpected_skips(self, vm_test_build: Build) -> bool:
    """Returns whether all test cases were attempted."""

    if vm_test_build.status == common_pb2.SUCCESS:
      return True

    failed_test_cases = vm_test_build.output.properties.get_or_create_list(
        'failed_test_cases')
    if not failed_test_cases:
      return False

    return all(
        jsonpb.MessageToDict(t).get('humanReadableSummary') !=
        MISSING_TEST_FAILURE_SUMMARY for t in failed_test_cases)
