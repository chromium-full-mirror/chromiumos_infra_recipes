# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for running recipes/support tools."""

from recipe_engine import recipe_api


class SupportApi(recipe_api.RecipeApi):
  """A module for support tool steps."""

  def initialize(self):
    self._pin = None
    self._ensured = False

  @property
  def _support_root(self):
    """Returns the path where the support CIPD package is installed."""
    return self.m.path['start_dir'].join('cros-recipes-support')

  def ensure_package_installed(self):
    """Ensure the CIPD support package is installed."""
    if not self._ensured:
      deploy_version_file = self.package_repo_resource(
          'support/deploy_cipd.json')

      step_data = self.m.json.read(
          'read deploy_cipd.json', deploy_version_file,
          step_test_data=lambda: self.m.json.test_api.output({
            'result': {'package': 'pkg', 'instance_id': 'inst'}
          }))
      version = step_data.json.output['result']

      ensure_file = self.m.cipd.EnsureFile()
      ensure_file.add_package(version['package'], version['instance_id'])
      self.m.cipd.ensure(self._support_root, ensure_file)
    self._ensured = True

  def call(self, tool, input_data):
    """Run a tool from the support package.

    Args:
      tool (str): Tool name.
      input_data: Data to be passed as input to the tool (serialized to JSON).

    Returns:
      Data passed as output from the tool (deserialized from JSON).
    """
    self.ensure_package_installed()
    tool_path = self._support_root.join(tool, tool)
    step_data = self.m.step(tool, [tool_path],
                            stdin=self.m.json.input(input_data),
                            stdout=self.m.json.output())
    return step_data.stdout
