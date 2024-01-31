# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.bot_scaling import BotPolicy
from PB.chromiumos.bot_scaling import ScalingAction
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'bot_scaling',
]



def RunSteps(api):
  bot_policy_config = api.bot_scaling.test_api.robocrop_bot_policy_config()
  test_config = api.bot_scaling.test_api.gce_provider_config()
  updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, test_config)
  for policy in updated_bot_policy.bot_policies:
    scaling_action = api.bot_scaling.get_scaling_action(90, policy, test_config)

    api.assertions.assertEqual(scaling_action.bots_requested, 110)
    api.assertions.assertEqual(scaling_action.bot_type,
                               api.bot_scaling.test_api.get_bot_type())
    api.assertions.assertEqual(scaling_action.bot_group, 'cq0')
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
        scaling_action.regional_actions[1].bots_requested, 28)

    api.assertions.assertEqual(scaling_action.regional_actions[2].region,
                               'third')
    api.assertions.assertEqual(scaling_action.regional_actions[2].prefix,
                               'prefix-third')
    api.assertions.assertEqual(
        scaling_action.regional_actions[2].bots_requested, 22)

    api.assertions.assertEqual(scaling_action.regional_actions[3].region,
                               'fourth')
    api.assertions.assertEqual(scaling_action.regional_actions[3].prefix,
                               'prefix-fourth')
    api.assertions.assertEqual(
        scaling_action.regional_actions[3].bots_requested, 33)

    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.YES)
    api.assertions.assertAlmostEqual(scaling_action.estimated_savings,
                                     2.2466667)

    # Request - min(current - request, step size) is less than configured,
    # scaling down.
    scaling_action = api.bot_scaling.get_scaling_action(40, policy, test_config)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.YES)
    api.assertions.assertEqual(scaling_action.bots_requested, 65)
    api.assertions.assertAlmostEqual(scaling_action.estimated_savings,
                                     4.7741671)

    # Request + step size is not less than configured.
    scaling_action = api.bot_scaling.get_scaling_action(70, policy, test_config)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.YES)
    api.assertions.assertEqual(scaling_action.bots_requested, 95)
    api.assertions.assertAlmostEqual(scaling_action.estimated_savings,
                                     3.0891669)

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

    api.assertions.assertAlmostEqual(scaling_action.estimated_savings,
                                     1.4041667)

    # Bots requested equals ceiling but less than step size
    ceiling_config = api.bot_scaling.test_api.gce_provider_config_ceiling()
    scaling_action = api.bot_scaling.get_scaling_action(150, policy,
                                                        ceiling_config)
    api.assertions.assertEqual(scaling_action.bots_requested, 150)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.YES)

    # BotScalingMode is set to STEPPED_DECREASE
    policy.scaling_mode = BotPolicy.STEPPED_DECREASE
    # BotsRequested should equal demand + min_idle.
    scaling_action = api.bot_scaling.get_scaling_action(100, policy,
                                                        test_config)
    api.assertions.assertEqual(scaling_action.bots_requested, 125)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.YES)

    api.assertions.assertAlmostEqual(scaling_action.estimated_savings,
                                     1.4041667)

    # Request - min(configured - request, step size) is less than configured,
    # scaling down.
    scaling_action = api.bot_scaling.get_scaling_action(40, policy, test_config)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.YES)
    api.assertions.assertEqual(scaling_action.bots_requested, 65)
    api.assertions.assertAlmostEqual(scaling_action.estimated_savings,
                                     4.7741671)

    # Monitored bot group
    policy.policy_mode = BotPolicy.MONITORED
    scaling_action = api.bot_scaling.get_scaling_action(90, policy, test_config)
    api.assertions.assertEqual(scaling_action.actionable, ScalingAction.NO)


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=1),
          build_pb2.Build(id=2),
          build_pb2.Build(id=3),
          build_pb2.Build(id=4),
          build_pb2.Build(id=5),
          build_pb2.Build(id=6),
      ], 'estimate time between builds.search for builds in past hour'),
  )
