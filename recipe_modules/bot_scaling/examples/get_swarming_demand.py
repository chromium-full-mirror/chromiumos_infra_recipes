# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  bot_policy_config = api.cros_infra_config.get_bot_policy_config()
  swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)

  test_stats = {'RUNNING': 23, 'PENDING': 23}
  test_demand = 0
  for _, count in test_stats.items():
    test_demand += count
  demand = api.bot_scaling.get_swarming_demand(swarming_stats, 'cq')
  api.assertions.assertEqual(test_demand, demand)


def GenTests(api):
  yield api.test('basic')
