# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
    'cros_infra_config',
]



def RunSteps(api):
  bot_policy_config = api.cros_infra_config.get_bot_policy_config()
  swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)
  api.assertions.assertEqual(len(swarming_stats.bot_stats), 1)
  for stat in swarming_stats.bot_stats:
    if stat.bot_group == 'cq':
      api.assertions.assertEqual(stat.busy, 21)
      api.assertions.assertEqual(stat.count, 23)
      api.assertions.assertEqual(stat.dead, 0)
      api.assertions.assertEqual(stat.maintenance, 0)
      api.assertions.assertEqual(stat.quarantined, 0)
      api.assertions.assertEqual(stat.min, 5)
      api.assertions.assertEqual(stat.max, 100)

  test_stats = {'RUNNING': 23, 'PENDING': 23}
  for stat in swarming_stats.task_stats:
    if stat.bot_group == 'cq':
      for state, count in test_stats.items():
        if stat.task_state == state:
          api.assertions.assertEqual(stat.count, count)


def GenTests(api):
  yield api.test('basic')
