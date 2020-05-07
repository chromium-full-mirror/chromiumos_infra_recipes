# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime

from recipe_engine import recipe_api

CHROMEOS_SWARMING_URL = 'chromeos-swarming.appspot.com'


class SwarmingCli(recipe_api.RecipeApi):
  """A module that queries Swarming via the CLI."""

  def __init__(self, *args, **kwargs):
    super(SwarmingCli, self).__init__(*args, **kwargs)
    self._version = 'latest'
    self._client = 'swarming.py'
    self._checkout = None

  def _ensure_checkout(self):
    """Ensures swarming client is checked out."""
    if self._checkout:
      return
    with self.m.context(infra_steps=True):
      cwd = self.m.path['cleanup'].join('swarming-client')
      self.m.git.checkout(
          'https://chromium.googlesource.com/infra/luci/client-py',
          dir_path=cwd, submodules=False)
      self._checkout = cwd
      self._client = cwd.join('swarming.py')

  def _run(self, name, cmd, test_stdout=None):
    """Return a swarming command step.

    Args:
      name: (str): name of the step.
      cmd (list[str]): swarming client subcommand to run.
    """
    self._ensure_checkout()
    return self.m.easy.stdout_json_step(
        name,
        [self._client] + list(cmd), test_stdout=test_stdout, infra_step=True)

  def get_bot_counts(self, dimensions=None):
    """Retrieves the count of bots from Swarming based on dimensions.

    Args:
      dimensions (tuple): string containing key, value dimensions to query swarming.
    """
    dim_args = []
    for dim in dimensions:
      dim_args.append('dimensions={}&'.format(dim))

    cmd = [
        'query', '--swarming', CHROMEOS_SWARMING_URL,
        'bots/count?' + ''.join(dim_args).rstrip('&')
    ]
    step = self._run(
        'get bot query result', cmd,
        test_stdout=lambda: self.test_api.swarming_bot_step_test_data(dimensions)
    )
    return step

  def get_task_counts(self, dimensions, state, lookback_hours):
    """Retrieves the count of tasks from Swarming based on dimensions.

    Args:
      dimensions (str): string containing key, value dimensions to query swarming.
      state (str): state of the tasks to query
      lookback_hours (int): Number of hours to query swarming on.
    """
    dim_args = ['state={}&'.format(state)]
    for dim in dimensions:
      dim_args.append('tags={}&'.format(dim))
    dim_args.append('start={}'.format(
        self._calculate_epoch_start(lookback_hours)))
    cmd = [
        'query', '--swarming', CHROMEOS_SWARMING_URL,
        'tasks/count?' + ''.join(dim_args).rstrip('&')
    ]
    step = self._run(
        'get task query result', cmd, test_stdout=
        lambda: self.test_api.swarming_task_step_test_data(dimensions))
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
    return ((self.m.time.utcnow() + datetime.timedelta(hours=hours_back)) -
            datetime.datetime(1970, 1, 1)).total_seconds()
