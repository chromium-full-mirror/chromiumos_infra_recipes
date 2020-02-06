# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format as jsonpb
from recipe_engine import recipe_api
from util import exponential_retry

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState
from PB.tast.test_result import TestResult

import os
import json
import ntpath

EXPECTED_FILES = ['log.txt', 'logcat.txt', 'messages', 'dummy_file']


class TastResultsApi(recipe_api.RecipeApi):
  """A module to process tast-results/ directory."""

  @exponential_retry(retries=3, condition=lambda e: e.had_timeout)
  def archive_results(self, test_results_path, gs_bucket):
    """Archive results to Google Storage.

    Args:
      test_results_path (Path): Path to test_results/.
      gs_bucket (str): GS bucket to upload to.
    """
    with self.m.step.nest('archive and upload test-results'):
      temp_archive_dir = self.m.path.mkdtemp('archive')
      archive_path = str(temp_archive_dir.join('tast_results.tgz'))
      self.m.archive.package(test_results_path).archive('archive test results',
                                                        archive_path)

      build = self.m.buildbucket.build
      upload_uri = 'gs://%s/%s/%s' % (gs_bucket, build.builder.builder,
                                      build.id)
      self.m.gsutil(['rsync', temp_archive_dir, upload_uri],
                    parallel_upload=True, multithreaded=True,
                    timeout=self.test_api.gsutil_timeout_seconds)
      self.m.easy.set_property_step('archive_link', upload_uri)

  def get_results(self, test_results_path, suite_name):
    """Return the test results decoded from the results.json.

    Args:
      test_results_path (Path): Path to test_results/.
      suite_name (str): Name of the whole test suite.

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
      if TaskState.VERDICT_FAILED in all_verdicts:
        overall_state.verdict = TaskState.VERDICT_FAILED
      return ExecuteResponse.TaskResult(name=suite_name, state=overall_state,
                                        attempt=0, test_cases=test_cases)

  def _read_results_json(self, test_results_path):
    """Read the results.json file and return structured contents.

    Args:
      test_results_path (Path): Path to test_results/.

    Returns:
      list(TestResult).
      https://crrev.com/62d6530f6f61417cf47a2bcea8bb714470ef5ca2/src/tast/test_result.proto
    """
    list_of_results = self.m.file.read_json(
        'read results.json', test_results_path.join('results.json'),
        test_data=self.test_api.test_results_json)
    return [
        jsonpb.ParseDict(result, TestResult()) for result in list_of_results
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

  def get_failures(self, task_result):
    """Convert TaskResult into api.failures.Failure objects.

    Args:
      task_result (TaskResult): TaskResult to be converted.

    Returns:
      list(Failure) of individual tests.
    """
    failures = []
    for test_case_result in task_result.test_cases:
      if test_case_result.verdict == TaskState.VERDICT_FAILED:
        failures.append(
            self.m.failures.Failure(
                kind='vm test',
                title=test_case_result.name,
                link_map={},
                fatal=True,
                id=None,
            ))

    return failures

  def print_results(self, task_result, test_results_path):
    """Print results for the user.

    Args:
      task_result(TaskResult): result of the run.
      test_results_path (Path): Path to test_results/.
    """
    with self.m.step.nest('print results') as step:
      step.presentation.step_text = (
          '' if task_result.state.verdict == TaskState.VERDICT_FAILED else
          'all tests passed!')
      for test_case_result in task_result.test_cases:
        if test_case_result.verdict == TaskState.VERDICT_FAILED:
          with self.m.step.nest(test_case_result.name) as step:
            step.presentation.step_text = (
                test_case_result.human_readable_summary[:50])
            step.presentation.status = self.m.step.FAILURE

            # Making a separate step so as to not show these to user.
            # This step should always be collapsed for end user.
            with self.m.step.nest('housekeeping'):
              test_log_dir = test_results_path.join('tests').join(
                  test_case_result.name)
              self.m.file.flatten_single_directories('flatten', test_log_dir)
              for file in self.m.file.listdir(
                  'ls', test_log_dir, test_data=['dummy_file'], recursive=True):
                # Strip dir from the name.
                filename = ntpath.basename(str(file))
                if filename in EXPECTED_FILES:
                  step.presentation.logs[filename] = self.m.file.read_text(
                      'reading file', file)

  def record_logs(self, sys_log_dir):
    """Print system logs to MILO.

    Args:
      sys_log_dir(str): absolute dir path to copy logs from.
    """
    with self.m.step.nest('record logs') as step:
      dump_dir = self.m.path.mkdtemp('var-log-dump')
      self.m.step('copy logs',
                  ['sudo', '-n', 'cp', '-rf', sys_log_dir,
                   str(dump_dir)])
      self.m.step('loosen permission',
                  ['sudo', '-n', 'chmod', '-R', '777',
                   str(dump_dir)])
      for file in self.m.file.listdir('ls', dump_dir, recursive=True,
                                      test_data=['kernel.log']):
        # Recipe doesn't like '/' in log name. Truncate the temp_dir
        # part of filename.
        filename = str(file).replace(os.sep, '-')[len(str(dump_dir)):]
        if str(file).endswith('.log'):
          step.presentation.logs[filename] = self.m.file.read_text(
              'reading file', file)
