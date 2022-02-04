# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class StableVersionApi(recipe_api.RecipeApi):
  """Module for issuing stable_version commands"""

  VALIDATE_TEST_SENTINEL = b'sentinel-386b2cca-9482-44cf-be26-6066d2c3796a'

  def initialize(self):
    self._cmd = None
    self._version = 'latest'

  def validate_stable_version(self):
    """Validate the remote stable version config file."""
    with self.m.step.nest('call stable_version2 to check remote file') as pres:
      self._ensure_stable_version()
      cmd = [
          self._cmd,
          "validate-config",
          "-remote-file",
      ]
      response = self.m.easy.stdout_step(
          'validate-config',
          cmd,
          test_stdout=StableVersionApi.VALIDATE_TEST_SENTINEL,
      )
      pres.logs['response'] = response
      return response

  def fetch_and_commit(self):
    """Fetch up-to-date stable version and commit them.

    Returns: response: raw string as the stdout data.
    """
    with self.m.step.nest('call stable_version2') as pres:
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
      pres.logs['response'] = response
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
