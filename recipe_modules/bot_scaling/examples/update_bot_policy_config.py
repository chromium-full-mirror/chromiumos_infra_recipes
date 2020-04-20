# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
    'cros_infra_config',
]

from PB.chromiumos.bot_scaling import BotPolicy, BotPolicyCfg


def RunSteps(api):
  bot_policy = api.bot_scaling.test_api.robocrop_bot_policy_config()
  bot_policy_config = BotPolicyCfg(bot_policies=[bot_policy])
  gce_config = api.bot_scaling.test_api.gce_provider_config()
  updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, gce_config)
  for policy in updated_bot_policy.bot_policies:
    api.assertions.assertEqual(policy.scaling_restriction.bot_ceiling, 150)
    api.assertions.assertEqual(policy.scaling_restriction.bot_floor, 20)

  bot_policy.policy_mode = BotPolicy.MONITORED
  bot_policy_config = BotPolicyCfg(bot_policies=[bot_policy])
  floor_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, gce_config)
  for policy in floor_bot_policy.bot_policies:
    api.assertions.assertEqual(policy.scaling_restriction.bot_ceiling, 150)
    api.assertions.assertEqual(policy.scaling_restriction.bot_floor, 25)


def GenTests(api):
  yield api.test('basic')
