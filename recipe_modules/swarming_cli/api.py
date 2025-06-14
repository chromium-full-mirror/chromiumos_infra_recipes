# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper functions for calling the swarming CLI."""

from typing import Iterable, Optional

from recipe_engine import config_types
from recipe_engine import recipe_api

_PKG_DEFAULT_REF = 'latest'


class SwarmingCli(recipe_api.RecipeApi):
  """A module that queries Swarming via the CLI."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    # Local path to the installed `swarming` CLI binary.
    self._cipd_bin: Optional[config_types.Path] = None

  def initialize(self) -> None:
    """Perform one-time module setup.

    This method is automatically called by the recipe engine once at the start
    of every recipe that depends on this module.
    """
    self._ensure_cipd_bin()

  def _ensure_cipd_bin(self):
    """Ensure that the CIPD swarming client is installed."""
    pkg_name = 'infra/tools/luci/swarming/${platform}'
    pkg_ref = _PKG_DEFAULT_REF
    with self.m.step.nest('ensure swarming bin from CIPD'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path.start_dir / 'cipd'
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(pkg_name, pkg_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)
        self._cipd_bin = cipd_dir / 'swarming'

  def _run_bin(self, name, cmd, test_stdout=None):
    """Return a swarming command step from the CIPD binary.

    Args:
      name: (str): name of the step.
      cmd (list[str]): swarming client subcommand to run.
    """
    return self.m.easy.stdout_json_step(name, [self._cipd_bin] + list(cmd),
                                        test_stdout=test_stdout,
                                        infra_step=True)

  def get_bot_counts(self, swarming_instance: str,
                     dimensions: Optional[Iterable[str]] = None,
                     bot_group: Optional[str] = None):
    """Retrieves the count of bots from Swarming based on dimensions.

    Args:
      swarming_instance: The name of the Swarming instance to query.
      dimensions: Iterable of strings formatted as "key:value" to query
          Swarming.
      bot_group: The name of the bot group for which to get the count.
    """
    cmd = ['bots', '-S', swarming_instance, '-count']
    for dim in dimensions:
      # Dims come delimited by ":", which is proper formatting for task queries.
      # But for bot queries, we need them to be delimited by "=".
      cmd.extend(['-dimension', dim.replace(':', '=')])
    step_name = 'get bot count query result'
    if bot_group:
      step_name = f'{step_name} for {bot_group}'
    step = self._run_bin(
        step_name, cmd, test_stdout=lambda: self.test_api.
        swarming_bot_step_test_data(dimensions))
    return step

  def get_task_counts(self, dimensions: Iterable[str], state: str,
                      lookback_hours: int, swarming_instance: str,
                      bot_group: Optional[str] = None):
    """Retrieves the count of tasks from Swarming based on filters.

    Args:
      dimensions: Iterable of strings formatted as 'key:value' to query
          Swarming.
      state: The state of the tasks to query
      lookback_hours: Number of hours to query swarming on.
      swarming_instance: The name of the Swarming instance to query.
      bot_group: The name of the bot group for which to get the count.
    """
    cmd = ['tasks', '-S', swarming_instance, '-count']
    cmd.extend(['-start', str(self._calculate_epoch_start(lookback_hours))])
    cmd.extend(['-state', state])
    for dim in dimensions:
      cmd.extend(['-tag', dim])
    step_name = 'get task count query result'
    if bot_group:
      step_name = f'{step_name} for {bot_group}'
    step = self._run_bin(
        step_name, cmd, test_stdout=lambda: self.test_api.
        swarming_task_step_test_data(dimensions))
    return step

  def _calculate_epoch_start(self, lookback_hours=-24):
    """Determines the epoch time needed for Swarming CLI task queries.

    Calculates current epoch time minus some number of hours.

    Args:
      lookback_hours (sint): signed int for number of hours to lookback
        for Swarming tasks.

    Returns:
      float, time since epoch in seconds.
    """
    hours_back = lookback_hours or -24
    return self.m.time.time() + hours_back * 3600
