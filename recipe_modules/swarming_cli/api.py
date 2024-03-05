# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper functions for calling the swarming CLI."""

import typing
from datetime import datetime

from recipe_engine import recipe_api

_PKG_DEFAULT_REF = 'latest'


class SwarmingCli(recipe_api.RecipeApi):
  """A module that queries Swarming via the CLI."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._cipd_bin = None

  def _ensure_cipd_bin(self):
    """Ensures the CIPD swarming client is installed."""
    if not self._cipd_bin:
      pkg_name = 'infra/tools/luci/swarming/${platform}'
      pkg_ref = _PKG_DEFAULT_REF
      with self.m.step.nest('ensure swarming bin from CIPD'):
        with self.m.context(infra_steps=True):
          cipd_dir = self.m.path['start_dir'].join('cipd')
          pkgs = self.m.cipd.EnsureFile()
          pkgs.add_package(pkg_name, pkg_ref)
          self.m.cipd.ensure(cipd_dir, pkgs)
          self._cipd_bin = cipd_dir.join('swarming')

  def _run_bin(self, name, cmd, test_stdout=None):
    """Return a swarming command step from the CIPD binary.

    Args:
      name: (str): name of the step.
      cmd (list[str]): swarming client subcommand to run.
    """
    self._ensure_cipd_bin()
    return self.m.easy.stdout_json_step(name, [self._cipd_bin] + list(cmd),
                                        test_stdout=test_stdout,
                                        infra_step=True)

  def get_bot_counts(self, swarming_instance: str,
                     dimensions: typing.Optional[typing.Iterable[str]] = None,
                     bot_group: typing.Optional[str] = None):
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

  def _swarming_time_to_datetime(self, time_str):
    format_str = '%Y-%m-%dT%H:%M:%S.%fZ'
    return datetime.strptime(time_str, format_str)

  def get_max_pending_time(self, dimensions, lookback_hours, swarming_instance):
    """Retrieves the list of tasks from Swarming based on dimensions.

    Args:
      dimensions (iterable): strings formatted as "key:value" to query Swarming.
      lookback_hours (int): Number of hours to query swarming on.
      swarming_instance(str): string containing the name of the Swarming
        instance to query.

    Returns:
      (float) Max pending time in hours.
    """
    tasks = self.get_task_list(dimensions, 'PENDING', lookback_hours,
                               swarming_instance, limit=1000)
    now = self.m.time.utcnow()
    oldest_time = now
    if tasks:
      oldest_time = self._swarming_time_to_datetime(tasks[-1]['created_ts'])
    # Hopefully there won't be tasks pending for days.
    return (now - oldest_time).seconds / 3600.0

  def get_task_list(self, dimensions, state, lookback_hours, swarming_instance,
                    limit=None):
    """Retrieves the list of tasks from Swarming based on dimensions and state.

    Args:
      dimensions (iterable): strings formatted as "key:value" to query Swarming.
      state (str): state of the tasks to query
      lookback_hours (int): Number of hours to query swarming on.
      swarming_instance(str): string containing the name of the Swarming
        instance to query.
      limit (int): Number of tasks to return.
    """
    cmd = ['tasks', '-S', swarming_instance]
    cmd.extend(['-start', str(self._calculate_epoch_start(lookback_hours))])
    cmd.extend(['-state', state])
    for dim in dimensions:
      cmd.extend(['-tag', dim])
    if limit:
      cmd.extend(['-limit', str(limit)])
    step = self._run_bin(
        'get task list query result', cmd,
        test_stdout=lambda: self.test_api.swarming_task_list_test_data(self.m))
    return step

  def get_task_counts(self, dimensions: typing.Iterable[str], state: str,
                      lookback_hours: int, swarming_instance: str,
                      bot_group: typing.Optional[str] = None):
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
