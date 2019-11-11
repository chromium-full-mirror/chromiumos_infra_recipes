# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

class StableVersionApi(recipe_api.RecipeApi):
  """Module for issuing stable_version commands"""

  def initialize(self):
    self._cmd = None
    self._version = 'latest'

  def fetch_and_commit(self):
    """Fetch up-to-date stable version and commit them.

    Returns: response: raw string as the stdout data.
    """
    with self.m.step.nest('call stable_version2') as s:
      self._ensure_stable_version()
      cmd = [
        self._cmd,
        "update-with-omaha",
      ]
      response = self.m.easy.stdout_step(
          'update-with-omaha',
          cmd,
          # TODO(xixuan): mock a more structured output.
          test_stdout='http://CL/123')
      s.presentation.logs['response'] = response
      return response

  def _ensure_stable_version(self):
    """Ensure the stable_version CLI is installed."""
    if self._cmd:
      return  # pragma: nocover

    with self.m.step.nest('ensure stable_version tool'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'stable_version2')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package('chromiumos/infra/stable_version2/${platform}',
                         self._version)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cmd = cipd_dir.join('stable_version2')