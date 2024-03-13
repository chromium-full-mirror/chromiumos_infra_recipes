# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for creating task URLs out of complex data structures."""

import collections
from typing import Dict

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.test_platform.taskstate import TaskState
from recipe_engine import recipe_api
from recipe_engine import step_data
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabTask

_LOGDOG_URL_TEMPLATE = (
    'https://%(logdog_hostname)s/logs/%(logdog_project)s/%(logdog_prefix)s/'
    '+/u/%(step_name)s/%(log_name)s')
VM_FAILURE_LINK_TEXT = 'test page'


class UrlsApi(recipe_api.RecipeApi):
  """A module for creating links to tasks."""

  def get_build_link_map(self, build: build_pb2.Build) -> Dict[str, str]:
    """Returns a {title->URL} for the given buildbucket build.

    Args:
      build: The buildbucket build in question.

    Returns:
      Dict of {title: URL} pointing to the build's MILO page.
    """
    link_url = self.m.buildbucket.build_url(build_id=build.id)
    return {'build page': link_url}

  def get_vm_test_link_map(self, vm_test: build_pb2.Build) -> Dict[str, str]:
    """Returns a {title: URL} dict for the given VM test build.

    Args:
      vm_test: The VM test build in question.

    Returns:
      Dict of {title: URL} pointing to the vm_test's MILO page.
      For direct-vm tests, the individual failing tests are listed.
    """
    link_url = self.m.buildbucket.build_url(build_id=vm_test.id)
    if 'failed_test_cases' in vm_test.output.properties and len(
        vm_test.output.properties['failed_test_cases']) > 0:
      prop_struct = vm_test.output.properties['failed_test_cases']
      failed_test_cases_json = json_format.MessageToDict(prop_struct)
      link_map = {}
      for test_case_json in failed_test_cases_json:
        if test_case_json['verdict'] == 'VERDICT_FAILED':
          link_map[test_case_json['name']] = link_url

      return link_map
    return {VM_FAILURE_LINK_TEXT: link_url}

  @staticmethod
  def get_skylab_task_url(skylab_task: SkylabTask) -> str:
    """Returns the URL to the given skylab task.

    Args:
      skylab_task: The Skylab task in question.

    Returns:
      URL pointing to the Swarming task page for the Skylab task.
    """
    return skylab_task.url

  def get_skylab_result_link_map(self,
                                 skylab_result: SkylabResult) -> Dict[str, str]:
    """Returns the URL to the given skylab result page.

    Args:
      skylab_task: The Skylab result in question.

    Returns:
      Dict of {title: URL} for the Skylab swarming task parge if the suite
      succeeded, or entries of just the failed tests.
    """
    ctp_url = self.get_skylab_task_url(skylab_result.task)
    failure_verdicts = (TaskState.VERDICT_FAILED, TaskState.VERDICT_UNSPECIFIED)
    if (skylab_result.status == common_pb2.SUCCESS or
        not skylab_result.child_results):
      return {'suite page': ctp_url}

    task_name_to_results = collections.defaultdict(list)
    for tr in skylab_result.child_results:
      task_name_to_results[tr.name].append(tr)

    def _good_attempt(result):
      # If it passed, that's a great attempt.
      if result.state.verdict not in failure_verdicts:
        return True

      # Otherwise, it is a good attempt if it passed provisioning and ran
      # tests.
      failed_provisioning = any(
          tr.verdict in failure_verdicts for tr in result.prejob_steps)
      ran_test_cases = len(result.test_cases) > 0
      return ran_test_cases and not failed_provisioning

    # With CFT and Tast First Class, CTP will only retry failed test cases.
    # Therefore, it is okay to just return the latest attempt where test cases
    # were actually executed. This should reduce noise when reporting failures.
    task_name_to_best_result = {}
    for name, results in task_name_to_results.items():
      results.sort(key=lambda x: x.attempt, reverse=True)
      # Return the latest "good" attempt. If none are "good" return the latest
      # attempt.
      default_best_attempt = results[0]
      task_name_to_best_result[name] = next(
          (x for x in results if _good_attempt(x)), default_best_attempt)

    link_map = {}
    for task_result in task_name_to_best_result.values():
      # Don't raise failure details for tasks that flaked.
      if task_result.state.verdict not in failure_verdicts:
        continue

      # If the prejob failed, do not attempt to return per-test case results.
      # Note: Prejob failures don't always contain a status or human readable
      # summary.
      if any(tc.verdict in failure_verdicts for tc in task_result.prejob_steps):
        for tc in task_result.prejob_steps:
          if tc.verdict in failure_verdicts:
            if tc.human_readable_summary:
              summary = tc.human_readable_summary.lower() or tc.name
              summary = summary[7:] if summary.startswith(
                  'reason_') else summary
            else:
              summary = tc.name + ' failed'
            fail_text = task_result.name + ' - ' + summary
            link_map[fail_text] = task_result.task_url
        continue

      # Return per-test case results if possible.
      test_cases_empty = len(task_result.test_cases) == 0 or (
          len(task_result.test_cases) == 1 and
          task_result.test_cases[0].verdict == TaskState.VERDICT_UNSPECIFIED)
      if (not test_cases_empty and
          task_result.state.life_cycle == TaskState.LIFE_CYCLE_COMPLETED):
        for tc in task_result.test_cases:
          if tc.verdict in failure_verdicts:
            case_name = tc.name
            if case_name == 'tast' and tc.human_readable_summary:
              case_name += ': ' + tc.human_readable_summary
            link_map[case_name] = task_result.task_url
      # If per-test case results are not available, return shard-level results.
      elif task_result.task_url:
        # When per-test results are not available.
        task_name = (
            task_result.name + self.get_state_suffix(task_result.state))
        link_map[task_name] = task_result.task_url
      # If the task is never scheduled there will be no task url (e.g. rejected
      # dimensions). In this case, link to the CTP page.
      else:
        task_name = (
            task_result.name + self.get_state_suffix(task_result.state))
        link_map[task_name] = ctp_url

    return link_map

  @staticmethod
  def get_state_suffix(task_state: TaskState) -> str:
    """Returns a string suffix to supply info about the task.

    Args:
      tast_state: The task state.

    Returns:
      A string denoting more information about the task.
    """
    if task_state.life_cycle == TaskState.LIFE_CYCLE_CANCELLED:
      return ' (canceled before starting)'
    if task_state.life_cycle == TaskState.LIFE_CYCLE_RUNNING:
      return ' (timed out while running)'
    if task_state.life_cycle == TaskState.LIFE_CYCLE_ABORTED:
      return ' (canceled while running)'
    if task_state.life_cycle == TaskState.LIFE_CYCLE_REJECTED:
      return ' (never ran, due to no DUT capacity)'
    if task_state.life_cycle == TaskState.LIFE_CYCLE_PENDING:
      return ' (timed out waiting for available DUT)'
    return ''

  @staticmethod
  def get_gs_path_url(gs_uri):
    """Returns the Cloud Storage Browser URL to the given GS path.

    Args:
      gs_uri: A string of the format "gs://<bucket>/<object>"

    Returns:
      URL pointing to the Cloud Storage Browser page for the object.
    """

    if not gs_uri.startswith('gs://'):
      raise ValueError('gs_uri argument must start with "gs://"')
    return 'https://storage.cloud.google.com/' + gs_uri[len('gs://'):]

  @staticmethod
  def get_gs_bucket_url(gs_bucket: str, gs_path: str) -> str:
    """Returns the Cloud Storage Browser URL given a bucket and path.

    Args:
      gs_bucket: A string of the gs bucket name to use
      gs_path: A string matching a path within that bucket

    Returns:
      URL pointing to the Cloud Storage Browser page matching the input.
    """
    return '/'.join([
        'https://console.cloud.google.com/storage/browser/_details', gs_bucket,
        gs_path
    ])

  def get_logdog_url(self, step: step_data.StepData, log_name: str,
                     use_top_level_step: bool = True) -> str:
    """Returns the LogDog URL for a step's log.

    buildbucket.build.infra.logdog is used to find the LogDog hostname, project,
    and prefix.

    Args:
      step: The step containing the log. Note that this should be the StepData
        for the step that actually ran, even if the log is attached to a
        higher-level nested step, see use_top_level_step.
      log_name: The name of the log added to a step. This can be a log that is
        automatically added to the step (e.g. "stdout") or a log added to
        StepPresentation.logs by the recipe.
      use_top_level_step: If true, point the URL to the highest-level step,
        otherwise point the URL to the step that actually ran (which may be
        nested). For example, the step is "outer step|run cmd" and
        use_top_level_step is true, the URL will be ".../outer_step/<log_name>",
        otherwise it will be ".../outer_step/run_cmd/<log_name>".

    Returns:
      The LogDog URL.
    """
    # If use_top_level_step, only take the first token, otherwise take all of
    # them.
    name_tokens = [step.name_tokens[0]
                  ] if use_top_level_step else step.name_tokens
    # Replace " " and "/" with "_", then join the tokens with "/".
    sanitized_name_tokens = [
        t.replace(' ', '_').replace('/', '_') for t in name_tokens
    ]
    step_name = '/'.join(sanitized_name_tokens)

    return _LOGDOG_URL_TEMPLATE % {
        'logdog_hostname': self.m.buildbucket.build.infra.logdog.hostname,
        'logdog_project': self.m.buildbucket.build.infra.logdog.project,
        'logdog_prefix': self.m.buildbucket.build.infra.logdog.prefix,
        'step_name': step_name,
        'log_name': log_name,
    }
