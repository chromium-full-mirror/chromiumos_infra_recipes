# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.gce.api.config.v1.config import Config
from PB.go.chromium.org.luci.gce.api.config.v1.config import Configs

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'bot_scaling',
    'cros_infra_config',
]



def RunSteps(api):
  bot_policy_config = api.bot_scaling.test_api.robocrop_bot_policy_config()
  swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)
  gce_config = api.bot_scaling.test_api.gce_provider_config()
  updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, gce_config)

  robocrop_action = api.bot_scaling.get_robocrop_action(
      updated_bot_policy, gce_config, swarming_stats=swarming_stats)

  vms = []
  prefix_map = {
      'prefix-first': 15,
      'prefix-second': 15,
      'prefix-third': 12,
      'prefix-fourth': 18
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
  yield api.test('basic')
