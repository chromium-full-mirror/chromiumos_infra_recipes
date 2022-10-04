# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for creating task URLs out of complex data structures."""

from recipe_engine import recipe_api
from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.taskstate import TaskState


class UrlsApi(recipe_api.RecipeApi):
  """A module for creating links to tasks."""

  # pylint: disable=unused-argument
  def __init__(self, properties, **kwargs):
    super(UrlsApi, self).__init__(**kwargs)

  def get_build_link_map(self, build):
    """Returns the title->URL to the given buildbucket build.

    Args:
      build (Build): The buildbucket build in question.

    Returns:
      str->str: title->URL pointing to the build milo page.
    """
    link_url = self.m.buildbucket.build_url(build_id=build.id)
    return {'build page': link_url}

  def get_vm_test_link_map(self, vm_test):
    """Returns the title->URL results from the given VM test.

    Args:
      vm_test (Build): The vm test in question.

    Returns:
      str->str: title->URL pointing to the vm_test's milo page.
        For direct-vm tests, the individual failing tests are listed.
    """
    link_url = self.m.buildbucket.build_url(build_id=vm_test.id)
    if 'failed_test_cases' in vm_test.output.properties:
      prop_struct = vm_test.output.properties['failed_test_cases']
      failed_test_cases_json = json_format.MessageToDict(prop_struct)
      link_map = {}
      for test_case_json in failed_test_cases_json:
        if test_case_json['verdict'] == 'VERDICT_FAILED':
          link_map[test_case_json['name']] = link_url

      return link_map
    return {'test page': link_url}

  def get_skylab_task_url(self, skylab_task):
    """Returns the URL to the given skylab task.

    Args:
      skylab_task (SkylabTask): The Skylab task in question.

    Returns:
      str: URL pointing to the skylab swarming task page.
    """
    return skylab_task.url

  def get_skylab_result_link_map(self, skylab_result):
    """Returns the URL to the given skylab result page.

    Args:
      skylab_task (SkylabResult): The Skylab result in question.

    Returns:
      str->str map: title to URL to the skylab swarming task page
      if the suite succeeded or entries of just the failed tests.
    """
    failure_verdicts = (TaskState.VERDICT_FAILED, TaskState.VERDICT_UNSPECIFIED)
    if (skylab_result.status == common_pb2.SUCCESS or
        not skylab_result.child_results):
      link_url = self.get_skylab_task_url(skylab_result.task)
      return {'suite page': link_url}
    link_map = {}
    for task_result in skylab_result.child_results:
      # Return per-test case results if possible.
      if (task_result.test_cases and
          task_result.state.life_cycle == TaskState.LIFE_CYCLE_COMPLETED):
        for tc in task_result.test_cases:
          if tc.verdict in failure_verdicts:
            case_name = tc.name
            if case_name == 'tast' and tc.human_readable_summary:
              case_name += ': ' + tc.human_readable_summary
            link_map[case_name] = task_result.task_url
      else:
        task_name = (
            task_result.name + self.get_state_suffix(task_result.state))
        if task_result.state.verdict in failure_verdicts:
          link_map[task_name] = task_result.task_url

    return link_map

  def get_state_suffix(self, task_state):
    """String suffix to supply info about the task.

    Args:
      tast_state(TaskState): The task state.

    Returns:
      str, denoting more information about the task.
    """
    if task_state.life_cycle == TaskState.LIFE_CYCLE_CANCELLED:
      return ' (was cancelled)'
    if task_state.life_cycle == TaskState.LIFE_CYCLE_RUNNING:
      return ' (timed out)'
    if task_state.life_cycle == TaskState.LIFE_CYCLE_ABORTED:
      return ' (was aborted)'
    if task_state.life_cycle == TaskState.LIFE_CYCLE_REJECTED:
      return ' (was rejected)'
    if task_state.life_cycle == TaskState.LIFE_CYCLE_PENDING:
      return ' (timed out waiting for available DUT)'
    return ''

  def get_gs_path_url(self, gs_path):
    """Returns the Cloud Storage Browser URL to the given GS path.

    Args:
      gs_path (str): A string of the format "gs://<bucket>/<object>"

    Returns:
      str: URL pointing to the Cloud Storage Browser page for the
        object.
    """

    if not gs_path.startswith('gs://'):
      raise ValueError('gs_path argument must start with "gs://"')

    return 'https://storage.cloud.google.com/' + gs_path[len('gs://'):]
