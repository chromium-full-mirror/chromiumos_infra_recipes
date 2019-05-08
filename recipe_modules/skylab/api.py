# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import recipe_api

from urlparse import urlparse

from RECIPE_MODULES.chromeos.test_plan.api import ScheduleResult

SKYLAB_VERSION = 'prod'


# swarming.TaskRequestMetadata duck.
# TestManager and TestPlan both expect to interact with
# TaskRequestMetadata type objects.
class SkylabRequestMetadata(object):
  """Metadata of a requested task."""

  def __init__(self, task_json, build_target, milo_display_name):
    self._task_json = task_json
    self._build_target = build_target
    self._milo_display_name = milo_display_name

  @property
  def name(self):
    """Returns the name of the associated task."""
    # This would normally come from self._task_json['task_name']
    # However, it's only ever used in our recipes as a name for referring
    # to test runs, so it's convenient to rename it to something prettier.
    return self._milo_display_name

  @property
  def id(self):
    """Returns the id of the associated task."""
    return self._task_json['task_id']  # pragma: nocover

  @property
  def task_ui_link(self):
    """Returns the URL of the associated task in the Swarming UI."""
    return self._task_json['task_url']

  @property
  def swarming_server(self):
    """Returns the swarming server hostname of the associated task."""
    return 'https://%s' % urlparse(self._task_json['task_url']).hostname

  @property
  def build_target(self):
    """Returns chromiumos.BuildTarget."""
    return self._build_target  # pragma: nocover


class SkylabApi(recipe_api.RecipeApi):
  """Skylab helper module"""
  def initialize(self):
    self._skylab_path = None

  def create_suites(self, name, test_unit):
    """Skylab step.

    Args:
      * name (str): Step name.
      * test_unit (TestUnit): Test plan step to execute.

    Returns:
      test_plan.api.ScheduleResult
    """
    self._ensure_skylab()

    tasks = []
    with self.m.step.nest(name):
      for test in test_unit.hw_test_cfg.hw_test:
        test_suite = test.suite
        skylab_pool = 'DUT_POOL_QUOTA'
        cmd = [
            self._skylab_path, 'create-suite',
            '-json',
            '-pool', skylab_pool,
            '-image', test_unit.build_payload.artifacts_gs_path,
            '-board', test.skylab_board,
            '-timeout-mins', 120,
            '-qs-account', 'cq',
            test_suite,
        ]

        result = self.m.easy.stdout_step(
            test_suite, cmd,
            test_stdout=self.test_api.example_result(test_suite))
        milo_display_name = '%s.hw.%s' % (test_unit.build_target.name, test_suite)
        task = SkylabRequestMetadata(
            json.loads(result), test_unit.build_target, milo_display_name)
        presented_links = self.m.step.active_result.presentation.links
        presented_links['Skylab task UI: %s' % task.name] = task.task_ui_link
        tasks.append(task)

    if tasks:
      swarming_server = tasks[0].swarming_server

    return ScheduleResult(swarming_server=swarming_server, tasks=tasks)

  def _ensure_skylab(self):
    """Ensure the Skylab cli is installed."""
    if self._skylab_path:
      return  # pragma: nocover

    with self.m.step.nest('ensure skylab'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'skylab')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/skylab/${platform}',
                          SKYLAB_VERSION)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._skylab_path = cipd_dir.join('skylab')
