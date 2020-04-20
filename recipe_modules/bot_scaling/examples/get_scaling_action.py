# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
]

from PB.chromiumos.bot_scaling import BotPolicy, BotPolicyCfg, ScalingAction


def RunSteps(api):
  bot_policy = api.bot_scaling.test_api.robocrop_bot_policy_config()
  bot_policy_config = BotPolicyCfg(bot_policies=[bot_policy])
  test_config = api.bot_scaling.test_api.gce_provider_config()
  updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, test_config)
  for policy in updated_bot_policy.bot_policies:
    scaling_action = api.bot_scaling.get_scaling_action(90, policy, test_config)

    api.assertions.assertEqual(scaling_action.bots_requested, 110)
    api.assertions.assertEqual(scaling_action.bot_type,
                               api.bot_scaling.test_api.get_bot_type())
    api.assertions.assertEqual(scaling_action.bot_group, 'cq')
    api.assertions.assertEqual(len(scaling_action.regional_actions), 4)
    api.assertions.assertEqual(scaling_action.regional_actions[0].region,
                               'first')
    api.assertions.assertEqual(scaling_action.regional_actions[0].prefix,
                               'prefix-first')
    api.assertions.assertEqual(
        scaling_action.regional_actions[0].bots_requested, 27)
    api.assertions.assertEqual(scaling_action.regional_actions[1].region,
                               'second')
    api.assertions.assertEqual(scaling_action.regional_actions[1].prefix,
                               'prefix-second')
    api.assertions.assertEqual(
        scaling_action.regional_actions[1].bots_requested, 27)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.YES)

    # Request - step size is less than configured, scaling down.
    scaling_action = api.bot_scaling.get_scaling_action(40, policy, test_config)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.NO)
    api.assertions.assertEqual(scaling_action.bots_requested, 60)

    # Request + step size is not less than configured.
    scaling_action = api.bot_scaling.get_scaling_action(70, policy, test_config)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.NO)

    # Demand is equal to number of bots configured
    scaling_action = api.bot_scaling.get_scaling_action(60, policy, test_config)
    api.assertions.assertEqual(scaling_action.bots_requested, 85)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.NO)

    # BotScalingMode is set to DEMAND
    # BotsRequested should equal demand + step size.
    policy.scaling_mode = BotPolicy.DEMAND
    scaling_action = api.bot_scaling.get_scaling_action(100, policy,
                                                        test_config)
    api.assertions.assertEqual(scaling_action.bots_requested, 125)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.YES)

    # Monitored bot group
    policy.policy_mode = BotPolicy.MONITORED
    scaling_action = api.bot_scaling.get_scaling_action(90, policy, test_config)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.NO)


def GenTests(api):
  yield api.test('basic')
