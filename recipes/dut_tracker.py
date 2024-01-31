# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Star Doctor.

Automatically updates binary config files and updates Goldeneye config
json files.
"""

from typing import Generator, List

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData
from PB.chromiumos.dut_tracking import MAX_PEND_TIME
from PB.chromiumos.dut_tracking import TrackingPolicyCfg

DEPS = [
    'recipe_engine/step',
    'cros_infra_config',
    'easy',
    'swarming_cli',
]


TASK_STATES = ['RUNNING', 'PENDING']


def RunSteps(api: RecipeApi) -> None:
  with api.step.nest('get config'):
    tracking_policies = (
        api.cros_infra_config.get_dut_tracking_config().policies)

  with api.step.nest('query swarming'):
    bot_stats = []
    task_stats = []
    pend_stats = []

    for policy in tracking_policies:
      with api.step.nest('querying ' + policy.name):
        dims = _bind_dimensions(policy.dimensions)
        task_dims = _bind_dimensions(policy.task_dimensions)
        bot_count = api.swarming_cli.get_bot_counts(policy.swarming_instance,
                                                    dims)
        bot_count['name'] = policy.name
        task_count = {'name': policy.name}
        for state in TASK_STATES:
          task_count[state] = api.swarming_cli.get_task_counts(
              dims + task_dims, state, policy.lookback_hours,
              policy.swarming_instance)

        if MAX_PEND_TIME in policy.modes:
          pend_time = {
              'name':
                  policy.name,
              'pend':
                  api.swarming_cli.get_max_pending_time(
                      dims + task_dims, policy.lookback_hours,
                      policy.swarming_instance)
          }
          pend_stats.append(pend_time)
        bot_stats.append(bot_count)
        task_stats.append(task_count)

    props = {'bot_stats': bot_stats, 'task_stats': task_stats}
    if pend_stats:
      props['pend_stats'] = pend_stats
    api.easy.set_properties_step(**props)


def _bind_dimensions(dimensions: TrackingPolicyCfg) -> List[str]:
  return ['{}:{}'.format(d.name, d.value) for d in dimensions]


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test('basic')
