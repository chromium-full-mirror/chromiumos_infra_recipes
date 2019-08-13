# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from collections import namedtuple
from google.protobuf import json_format

from recipe_engine import recipe_api

import structs

from PB.test_platform.skylab_tool.result import WaitTasksResult

class SkylabApi(recipe_api.RecipeApi):
  """Module for issuing commands to Skylab"""

  SkylabTask = structs.SkylabTask
  SkylabResult = structs.SkylabResult

  def __init__(self, properties, **kwargs):
    super(SkylabApi, self).__init__(**kwargs)
    self._server = str(properties.skylab_server) or 'https://chromeos-swarming.appspot.com'
    # TODO(crbug.com/991703): Once there is a meaninful cipd package tag that
    # corresponds to a CI-blessed version of the skylab tool, track it
    # instead of the "latest" tag.
    self._version = str(properties.skylab_version) or 'latest'
    self._qs_account = str(properties.skylab_qs_account) or 'pcq'
    self._skylab_timeout = str(properties.skylab_timeout) or '7h'

  def initialize(self):
    self._client = None

  def create_suite(self, test, unit, name=None, bb=False):
    """Schedule a HW test suite.

    Args:
      test (HwTest): A hardware test config.
      unit (HwTestUnit): The unit the test was defined in.
      name (str): The step name. Defaults to 'schedule <test title>'
      bb (boolean): Whether to use buildbucket-backed cros_test_platform.
                    Note: this flag is temporary, and will exist only during
                    cros_test_platform migration.

    Returns:
      SkylabTask: The swarming task ID.
    """
    self._ensure_skylab()
    name = name or 'schedule %s' % test.common.display_name
    with self.m.step.nest(name) as step:
      cmd = [
          self._client,
          'create-suite',
          '-bb=' + repr(bb),
          '-json',
          '-pool',
          'DUT_POOL_QUOTA',
          '-image',
          unit.common.build_payload.artifacts_gs_path,
          '-board',
          test.skylab_board,
          '-timeout-mins',
          7 * 60,  # 7 hours to account for skylab capacity under strain.
          '-qs-account',
          self._qs_account,
          '-task-name',
          test.common.display_name,
          test.suite,
      ]
      task_json = self.m.easy.stdout_json_step(
          'skylab create-suite', cmd, infra_step=True,
          test_stdout=self.test_api.create_suite_json_output(test.suite))
      task_id = task_json['task_id']
      task_url = task_json['task_url']
      step.presentation.links['swarming task'] = task_url
      return self.SkylabTask(id=task_id, url=task_url, test=test, unit=unit)

  def wait_tasks(self, tasks, bb=False):
    """Wait for all Skylab suites to finish and return the results.

    Uses skylab wait-tasks internally.

    Args:
      tasks (list[SkylabTask]): The Skylab tasks to wait on.
      bb (boolean): Whether to use buildbucket-backed cros_test_platform.
                    Note: this flag is temporary, and will exist only during
                    cros_test_platform migration.

    Returns:
      list[SkylabResult]: The results for each suite.
    """
    self._ensure_skylab()
    tasks_by_id = {task.id: task for task in tasks}

    with self.m.step.nest('collect skylab tasks') as step:
      task_ids = [task.id for task in tasks]
      # TODO(crbug.com/989623) once wait-tasks supports partial results
      # drop the extra 10 min wait.
      cmd = [
          self._client, 'wait-tasks', '-bb=' + repr(bb), '-timeout-mins',
          7 * 60 + 10
      ]
      cmd += task_ids
      output_json = self.m.easy.stdout_json_step(
          'skylab wait-tasks', cmd, infra_step=True, ignore_exceptions=True,
          test_stdout=self.test_api.wait_tasks_json_output())

      # Convert parsed-json python dictionary into proto.
      wait_results = WaitTasksResult()
      json_format.Parse(json.dumps(output_json), wait_results)

      results = []
      for wait_result in wait_results.results:
        task_result = wait_result.result
        task_id = task_result.task_request_id
        task_name = tasks_by_id[task_id].test.common.display_name
        task_url = task_result.task_run_url
        step.presentation.links[task_name] = task_url
        # TODO(dhanyaganesh): output seems to be unused.
        results.append(
            self.SkylabResult(task=tasks_by_id[task_id],
                              success=task_result.success, output=None))

      step.presentation.logs['return value'] = [str(x) for x in results]
      return results

  def _ensure_skylab(self):
    """Ensure the Skylab CLI is installed."""
    if self._client:
      return  # pragma: nocover

    with self.m.step.nest('ensure skylab'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'skylab')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/skylab/${platform}', self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._client = cipd_dir.join('skylab')
