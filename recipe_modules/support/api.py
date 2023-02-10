# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for running recipes/support tools."""

from recipe_engine import recipe_api


class SupportApi(recipe_api.RecipeApi):
  """A module for support tool steps."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._properties = properties

  def initialize(self):
    self._support_cipd_path = None

    self._support_cipd_package = (
        self._properties.support_cipd_package or
        'chromiumos/infra/support/${platform}')

    # This module gets used before cros_infra_config loads builder config
    # (and calling cros_infra_config would create a circular dependency),
    # so we have to do our own check.
    build = self.m.buildbucket.build
    is_staging = (
        build.builder.bucket == 'staging' or
        build.builder.builder.startswith('staging-'))
    default_ref = 'staging' if is_staging else 'prod'
    self._support_cipd_ref = (self._properties.support_cipd_ref or default_ref)

  def ensure_package_installed(self):
    """Ensure the CIPD support package is installed."""
    if self._support_cipd_path:
      return

    with self.m.step.nest('ensure support CIPD package'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd-support')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._support_cipd_package, self._support_cipd_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._support_cipd_path = cipd_dir

  def call(self, tool, input_data, test_output_data=None, infra_step=True,
           timeout=None, add_json_log=True, **kwargs):
    """Run a tool from the support package.

    Args:
      tool (str): Tool name.
      input_data: Data to be passed as input to the tool (serialized to JSON).
      test_output_data (dict|list|Callable): Data to return in tests.
      infra_step (bool): Whether or not this is an infrastructure step.
      timeout (int): Timeout of the step in seconds.
      add_json_log (bool): Log the content of the output json.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      Data passed as output from the tool (deserialized from JSON).
    """
    self.ensure_package_installed()
    tool_path = self._support_cipd_path.join(tool)
    return self.m.easy.stdout_json_step(tool, [tool_path],
                                        stdin_json=input_data,
                                        test_stdout=test_output_data,
                                        infra_step=infra_step, timeout=timeout,
                                        add_json_log=add_json_log, **kwargs)
