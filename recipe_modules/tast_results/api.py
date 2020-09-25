# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format as jsonpb
from recipe_engine import recipe_api
from recipe_engine.util import exponential_retry

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState
from PB.tast.test_result import TestResult

PANTHEON_PREFIX = 'https://pantheon.corp.google.com/storage/browser'
GS_BUCKET = 'chromeos-vmtest-archive'
FAILURE_VERDICTS = [TaskState.VERDICT_FAILED, TaskState.VERDICT_UNSPECIFIED]


class TastResultsApi(recipe_api.RecipeApi):
  """A module to process tast-results/ directory."""

  @exponential_retry(retries=3, condition=lambda e: getattr(e, 'had_timeout', False))
  def archive_dir(self, dir_path, tag):
    """Archive dir to Google Storage.

    Args:
      dir_path (Path): Path to dir to be uploaded.
      tag (str): Tag for this execution. Used to distinguish archive folders.

    Returns:
      str, link to the archive on pantheon.
    """
    with self.m.step.nest('GS upload ' + tag) as presentation:
      build = self.m.buildbucket.build
      upload_uri = 'gs://%s/%s/%s/%s' % (GS_BUCKET, build.builder.builder,
                                         build.id, tag)
      self.m.gsutil(['rsync', '-r', dir_path, upload_uri], parallel_upload=True,
                    multithreaded=True,
                    timeout=self.test_api.gsutil_timeout_seconds)
      pantheon_url = '%s/%s/%s/%s/%s' % (PANTHEON_PREFIX, GS_BUCKET,
                                         build.builder.builder, build.id, tag)
      presentation.links['archive_link'] = pantheon_url
      return pantheon_url

  def get_results(self, test_results_path, suite_name, tag, tests):
    """Return the test results decoded from the results.json.

    Args:
      test_results_path (Path): Path to test_results/.
      suite_name (str): Name of the whole test suite.
      tag (str): Tag for this execution. Used to distinguish archive folders.
      tests list(str): List of tests that were executed.

    Returns:
      A consolidated Data Structure summarizing all results from a run.
      Currently this is a TaskResult.
      https://crrev.com/ee30a869473a8ee54246e0469ede2aa010fb2e48/src/test_platform/steps/execution.proto#47
    """
    with self.m.step.nest('process tast output'):
      test_results = self._read_results_json(test_results_path)
      test_cases = [self.convert_to_testcaseresult(r) for r in test_results]

      # If even one test failed, the suite should report failure.
      all_verdicts = [t.verdict for t in test_cases]
      overall_state = TaskState(verdict=TaskState.VERDICT_PASSED,
                                life_cycle=TaskState.LIFE_CYCLE_COMPLETED)
      log_url = self.archive_dir(test_results_path, tag + '_results')

      if len(test_cases) < len(tests):  #pragma: nocover
        overall_state.verdict = TaskState.VERDICT_FAILED
        test_cases += self.missing_test_cases(tests, test_cases)
      elif TaskState.VERDICT_FAILED in all_verdicts:
        overall_state.verdict = TaskState.VERDICT_FAILED
      return ExecuteResponse.TaskResult(name=suite_name, state=overall_state,
                                        log_url=log_url, attempt=0,
                                        test_cases=test_cases)

  def _read_results_json(self, test_results_path):
    """Read the results.json file and return structured contents.

    Args:
      test_results_path (Path): Path to test_results/.

    Returns:
      list(TestResult).
      https://crrev.com/62d6530f6f61417cf47a2bcea8bb714470ef5ca2/src/tast/test_result.proto
    """
    try:
      list_of_results = self.m.file.read_json(
          'read results.json', test_results_path.join('results.json'),
          test_data=self.test_api.test_results_json)
    except self.m.file.Error:  # pragma: nocover
      # if results.json doesn't exist.
      list_of_results = []
    finally:
      # If results.json is an empty file, list_of_results will be None.
      list_of_results = list_of_results or []
    return [
        jsonpb.ParseDict(result, TestResult(), ignore_unknown_fields=True)
        for result in list_of_results
    ]

  def missing_test_cases(self, tests, test_cases):
    """Create missing tests cases.
    
    Args:
      tests list(str): list of tests that should have run.
      test_cases list(TestCaseResult): test_cases in the results.json.
    
    Returns: list(TestCaseResult) the missing tests cases.
    """
    reported_tests = set([tc.name for tc in test_cases])
    return [
        ExecuteResponse.TaskResult.TestCaseResult(
            name=test, verdict=TaskState.VERDICT_FAILED,
            human_readable_summary='Test did not run')
        for test in tests
        if test not in reported_tests
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

  def get_failures(self, task_result, exclude_tests=None):
    """Convert TaskResult into api.failures.Failure objects and dicts.

    Args:
      task_result (TaskResult): TaskResult to be converted.
      exclude_tests list(str): List of names of tests to be
        excluded.

    Returns:
      A tuple of list(Failure) and list(dict) representing
      failed test cases excluding the ones provided.
    """
    failures = []
    failed_test_cases = []
    exclude_tests = exclude_tests or []
    for test_case in task_result.test_cases:
      if test_case.verdict == TaskState.VERDICT_FAILED:
        if test_case.name not in exclude_tests:
          failures.append(
              self.m.failures.Failure(
                  kind='vm test',
                  title=test_case.name,
                  link_map={
                      test_case.human_readable_summary[:50]:
                          ('%s/tests/%s' % (task_result.log_url, test_case.name)
                          )
                  },
                  fatal=True,
                  id=None,
              ))
          failed_test_cases.append(jsonpb.MessageToDict(test_case))

    return failures, failed_test_cases

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
