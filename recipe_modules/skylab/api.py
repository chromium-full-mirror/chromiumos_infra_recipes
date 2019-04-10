# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import recipe_api

SKYLAB_SWARMING_POOL = 'ChromeOSSkylab'
SKYLAB_VERSION = 'prod'


# swarming.TaskRequestMetadata duck.
# TestManager and TestPlan both expect to interact with
# TaskRequestMetadata type objects.
class SkylabRequestMetadata(object):
  """Metadata of a requested task."""

  def __init__(self, task_json):
    self._task_json = task_json

  @property
  def name(self):
    """Returns the name of the associated task."""
    return self._task_json['task_name']  # pragma: nocover

  @property
  def id(self):
    """Returns the id of the associated task."""
    return self._task_json['task_id']  # pragma: nocover

  @property
  def task_ui_link(self):
    """Returns the URL of the associated task in the Swarming UI."""
    return self._task_json['task_url']  # pragma: nocover


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
      list[SkylabRequestMetadata]
    """
    self._ensure_skylab()

    tasks = []
    with self.m.step.nest(name):
      for test in test_unit.hw_test_cfg.hw_test:
        test_suite = test.suite
        cmd = [
            self._skylab_path, 'create-suite', '-json', '-pool',
            SKYLAB_SWARMING_POOL, '-image',
            test_unit.build_payload.artifacts_gs_path, '-board',
            test_unit.scheduling_requirements.build_target, test_suite
        ]

        result = self.m.easy.stdout_step(
            test_suite, cmd,
            test_stdout=self.test_api.example_result(test_suite))
        task = SkylabRequestMetadata(json.loads(result))
        tasks.append(task)

    return tasks

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
