# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from datetime import datetime
from datetime import timedelta

from recipe_engine import recipe_api


_PKG_INSTANCE = "rwv6c0O12emItRR5j8EA8-wMOwg_yAQRpZKB4wurRgkC"


class SwarmingCli(recipe_api.RecipeApi):
  """A module that queries Swarming via the CLI."""

  def __init__(self, *args, **kwargs):
    super(SwarmingCli, self).__init__(*args, **kwargs)
    # TODO(b/186120266): Replace all Python-based methods with CIPD,
    # and remove Python client/checkout.
    self._py_client = 'swarming.py'
    self._py_checkout = None
    self._cipd_bin = None

  def _ensure_py_checkout(self):
    """Ensures the Python swarming client is checked out."""
    if not self._py_checkout:
      with self.m.context(infra_steps=True):
        cwd = self.m.path['cleanup'].join('swarming-client')
        self.m.git.checkout(
            'https://chromium.googlesource.com/infra/luci/client-py',
            ref='14cadf852292035c5dc145de47f8af1000c9897a', dir_path=cwd,
            submodules=False)
        self._py_checkout = cwd
        self._py_client = cwd.join('swarming.py')

  def _ensure_cipd_bin(self):
    """Ensures the CIPD swarming client is installed."""
    if not self._cipd_bin:
      pkg_name = "infra/tools/luci/swarming/${platform}"
      pkg_ref = _PKG_INSTANCE
      with self.m.step.nest('ensure swarming bin from CIPD'):
        with self.m.context(infra_steps=True):
          cipd_dir = self.m.path['start_dir'].join('cipd')
          pkgs = self.m.cipd.EnsureFile()
          pkgs.add_package(pkg_name, pkg_ref)
          self.m.cipd.ensure(cipd_dir, pkgs)
          self._cipd_bin = cipd_dir.join('swarming')

  def _run_py(self, name, cmd, test_stdout=None):
    """Return a swarming command step from the Python client.

    Args:
      name: (str): name of the step.
      cmd (list[str]): swarming client subcommand to run.
    """
    self._ensure_py_checkout()
    return self.m.easy.stdout_json_step(name, [self._py_client] + list(cmd),
                                        test_stdout=test_stdout,
                                        infra_step=True)

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

  def get_bot_counts(self, swarming_instance, dimensions=None):
    """Retrieves the count of bots from Swarming based on dimensions.

    Args:
      swarming_instance(str): string containing the name of the Swarming
        instance to query.
      dimensions (iterable): strings formatted as "key:value" to query Swarming.
    """
    cmd = ['bots', '-S', swarming_instance, '-count']
    for dim in dimensions:
      # Dims come delimited by ":", which is proper formatting for task queries.
      # But for bot queries, we need them to be delimited by "=".
      cmd.extend(['-dimension', dim.replace(':', '=')])
    step = self._run_bin(
        'get bot query result', cmd, test_stdout=lambda: self.test_api.
        swarming_bot_step_test_data(dimensions))
    return step

  def _swarming_time_to_datetime(self, time_str):
    format_str = '%Y-%m-%dT%H:%M:%S.%f'
    return datetime.strptime(time_str, format_str)

  def get_max_pending_time(self, dimensions, lookback_hours, swarming_instance):
    """Retrieves the list of tasks from Swarming based on dimensions.

    Args:
      dimensions (str): string containing key, value dimensions to query swarming.
      lookback_hours (int): Number of hours to query swarming on.
      swarming_instance(str): string containing the name of the Swarming
        instance to query.

    Returns:
      (float) Max pending time in hours.
    """
    task_list = self.get_task_list(dimensions, 'PENDING', lookback_hours,
                                   swarming_instance, limit=1000)
    now = self._swarming_time_to_datetime(task_list['now'])
    oldest_time = now
    items = task_list.get('items', [])
    if items:
      oldest_time = self._swarming_time_to_datetime(items[-1]['created_ts'])
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
    query_args = ['state={}'.format(state)]
    for dim in dimensions:
      query_args.append('tags={}'.format(dim))
    query_args.append('start={}'.format(
        self._calculate_epoch_start(lookback_hours)))
    cmd = [
        'query', '--swarming', swarming_instance,
        'tasks/list?' + '&'.join(query_args)
    ]
    if limit:
      cmd += ['--limit', str(limit)]
    step = self._run_py(
        'get task query result', cmd, test_stdout=lambda: self.test_api.
        swarming_task_list_test_data(dimensions))
    return step

  def get_task_counts(self, dimensions, state, lookback_hours,
                      swarming_instance):
    """Retrieves the count of tasks from Swarming based on filters.

    Args:
      dimensions (iterable): strings formatted as 'key:value' to query Swarming.
      state (str): state of the tasks to query
      lookback_hours (int): Number of hours to query swarming on.
      swarming_instance(str): string containing the name of the Swarming
        instance to query.
    """
    cmd = ['tasks', '-S', swarming_instance, '-count']
    cmd.extend(['-start', str(self._calculate_epoch_start(lookback_hours))])
    cmd.extend(['-state', state])
    for dim in dimensions:
      cmd.extend(['-tag', dim])
    step = self._run_bin(
        'get task query result', cmd, test_stdout=lambda: self.test_api.
        swarming_task_step_test_data(dimensions))
    return step

  def _calculate_epoch_start(self, lookback_hours=-24):
    """Determines the epoch time needed for Swarming CL task queries.

    Calculates current epoch time minus twenty-four hour delta.

    Args:
      lookback_hours (sint): signed int for number of hours to lookback
        for Swarming tasks.

    Returns:
      float, time since epoch in seconds.
    """
    hours_back = lookback_hours or -24
    return ((self.m.time.utcnow() + timedelta(hours=hours_back)) -
            datetime(1970, 1, 1)).total_seconds()
