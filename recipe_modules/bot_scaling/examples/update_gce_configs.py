# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'bot_scaling',
    'cros_infra_config',
]

from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.go.chromium.org.luci.gce.api.config.v1.config import Config, Configs


def RunSteps(api):
  bot_policy = api.bot_scaling.test_api.robocrop_bot_policy_config()
  bot_policy_config = BotPolicyCfg(bot_policies=[bot_policy])
  gce_config = api.bot_scaling.test_api.gce_provider_config()
  updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, gce_config)
  status_map = {'cq': {'STARTED': 1000, 'SCHEDULED': 50}}

  robocrop_action = api.bot_scaling.get_robocrop_action(
      status_map, updated_bot_policy, gce_config)

  vms = []
  prefix_map = {
      'prefix-first': 22,
      'prefix-second': 22,
      'prefix-third': 18,
      'prefix-fourth': 27
  }
  for prefix, amount in prefix_map.items():
    vms.append(Config(prefix=prefix, current_amount=amount))
  gce_configs = Configs(vms=vms)
  configs = api.bot_scaling.update_gce_configs(robocrop_action, gce_configs)

  api.assertions.assertEqual(len(configs.vms), 4)

  for config in configs.vms:
    api.assertions.assertIn(config.prefix, prefix_map)
    api.assertions.assertEqual(config.current_amount,
                               prefix_map.get(config.prefix, None))


def GenTests(api):
  yield (api.test('basic') + api.buildbucket.simulated_search_results(
      [api.bot_scaling.previous_robocrop()],
      'find matching builds.buildbucket.search'))
