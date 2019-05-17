# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple

from recipe_engine import recipe_api

import structs


class SkylabApi(recipe_api.RecipeApi):
  """Module for issuing commands to Skylab"""

  SkylabTask = structs.SkylabTask
  SkylabResult = structs.SkylabResult

  def __init__(self, skylab_server, skylab_version, **kwargs):
    super(SkylabApi, self).__init__(**kwargs)
    self._server = skylab_server
    self._version = skylab_version

  def initialize(self):
    self._client = None

  def create_suite(self, test, payload, name=None):
    """Schedule a HW test suite.

    Args:
      test (HwTest): A hardware test config.
      payload (BuildPayload): The build payload for the target under test.
      name (str): The step name. Defaults to 'schedule <test title>'

    Returns:
      SkylabTask: The swarming task ID.
    """
    self._ensure_skylab()
    name = name or 'schedule %s' % test.common.display_name
    with self.m.step.nest(name) as step:
      cmd = [
          self._client,
          'create-suite',
          '-json',
          '-pool',
          'DUT_POOL_QUOTA',
          '-image',
          payload.artifacts_gs_path,
          '-board',
          test.skylab_board,
          '-timeout-mins',
          8 * 60, # 8 hours to account for skylab capacity under strain.
          '-qs-account',
          'cq',
          '-task-name',
          test.common.display_name,
          test.suite,
      ]
      task_json = self.m.easy.stdout_json_step(
          'skylab create-suite', cmd,
          test_stdout=self.test_api.create_suite_json_output(test.suite))
      step.presentation.links['swarming task'] = task_json['task_url']
      return self.SkylabTask(task_json['task_id'], test)

  def wait_suites(self, tasks):
    """Wait for all Skylab suites to finish executing and return the results.

    Args:
      tasks (list[SkylabTask]): The Skylab tasks to wait on.

    Returns:
      list[SkylabResult]: The results for each suite.
    """
    assert tasks, 'must supply at least one SkylabTask to wait_suites'

    tasks_by_id = {task.id: task for task in tasks}

    # TODO(evanhernandez): This should call skylab wait-suite, not swarming.
    with self.m.swarming.with_server(self._server):
      results = self.m.swarming.collect('collect skylab tasks',
                                        tasks_by_id.keys())

    return [
        self.SkylabResult(task=tasks_by_id[result.id], success=result.success,
                          output=result.output) for result in results
    ]

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
