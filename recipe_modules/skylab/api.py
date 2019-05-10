# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

class SkylabApi(recipe_api.RecipeApi):
  """Skylab helper module"""

  def __init__(self, skylab_version, **kwargs):
    super(SkylabApi, self).__init__(**kwargs)
    self._skylab_version = skylab_version

  def initialize(self):
    self._skylab_path = None

  def create_suite(self, test, payload, name=None):
    """Schedule a HW test suite.

    Args:
      test (HwTest): A hardware test config.
      payload (BuildPayload): The build payload for the target under test.
      name (str): The step name. Defaults to 'schedule <test title>'

    Returns:
      str: The swarming task ID.
    """
    self._ensure_skylab()
    name = name or 'schedule %s' % self.m.naming.get_hw_test_title(test)
    with self.m.step.nest(name) as step:
      cmd = [
          self._skylab_path,
          'create-suite',
          '-json',
          '-pool',
          'DUT_POOL_QUOTA',
          '-image',
          payload.artifacts_gs_path,
          '-board',
          test.skylab_board,
          '-timeout-mins',
          120,
          '-qs-account',
          'cq',
          test.suite,
      ]
      task_json = self.m.easy.stdout_json_step(
          'skylab create-suite', cmd,
          test_stdout=self.test_api.create_suite_json_output(test.suite))
      step.presentation.links['swarming task'] = task_json['task_url']
      return task_json['task_id']

  def _ensure_skylab(self):
    """Ensure the Skylab CLI is installed."""
    if self._skylab_path:
      return  # pragma: nocover

    with self.m.step.nest('ensure skylab'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'skylab')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/skylab/${platform}',
                         self._skylab_version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._skylab_path = cipd_dir.join('skylab')
