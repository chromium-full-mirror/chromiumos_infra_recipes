# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Star Doctor.

Automatically updates binary config files and updates Goldeneye config
json files.
"""

DEPS = [
    'recipe_engine/step',
    'cros_infra_config',
    'easy',
    'swarming_cli',
]

TASK_STATES = ['RUNNING', 'PENDING']


def RunSteps(api):
  with api.step.nest('get config'):
    tracking_policies = (
        api.cros_infra_config.get_dut_tracking_config().policies)

  with api.step.nest('query swarming'):
    bot_stats = {}
    task_stats = {}

    for policy in tracking_policies:
      with api.step.nest('querying ' + policy.name):
        dims = _bind_dimensions(policy.dimensions)
        bot_count = api.swarming_cli.get_bot_counts(dims)
        task_count = {}
        for state in TASK_STATES:
          task_count[state] = api.swarming_cli.get_task_counts(
              dims, state, policy.lookback_hours)

        bot_stats[policy.name] = bot_count
        task_stats[policy.name] = task_count

    api.easy.set_property_step('bot_stats', bot_stats)
    api.easy.set_property_step('task_stats', task_stats)


def _bind_dimensions(dimensions):
  return ['{}:{}'.format(d.name, d.value) for d in dimensions]


def GenTests(api):
  yield api.test('basic')
