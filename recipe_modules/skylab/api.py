# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

SKYLAB_SWARMING_POOL = 'ChromeOSSkylab'
SKYLAB_VERSION = 'prod'

class SkylabApi(recipe_api.RecipeApi):
  """Skylab helper module"""
  def initialize(self):
    self._skylab_path = None

  def create_suite(self, name, test_unit):
    """Skylab step.

    Args:
      * test_unit (TestUnit): Test plan step to execute.
    """

    self._ensure_skylab()

    # TODO(yshaul): Change to reference design when available. crbug/926512
    cmd = [
        self._skylab_path, 'create-suite', '-pool', SKYLAB_SWARMING_POOL,
        '-image', test_unit['build_payload']['image'][0]['image_name'],
        '-board', test_unit['scheduling_requirements']['build_target'],
        test_unit['test_suite']
    ]

    self.m.step(name, cmd)

    # TODO(yshaul): Replace hw-test with swarming metadata for skylab tasks. crbug/935244
    return 'hw-test'

  def _ensure_skylab(self):
    """Ensure the Skylab cli is installed."""
    if self._skylab_path:
      return

    with self.m.step.nest('ensure skylab'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'skylab')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/skylab/${platform}',
                          SKYLAB_VERSION)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._skylab_path = cipd_dir.join('skylab')
