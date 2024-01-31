# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.chromiumos.bot_scaling import ScalingAction

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'bot_scaling',
    'cros_infra_config',
]



def RunSteps(api):
  bot_policy_config = api.cros_infra_config.get_bot_policy_config()
  swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)
  robocrop_swarming_action = api.bot_scaling.get_robocrop_action(
      bot_policy_config, api.bot_scaling.test_api.gce_provider_config(),
      swarming_stats=swarming_stats)
  for action in robocrop_swarming_action.scaling_actions:
    api.assertions.assertEqual(action.actionable, ScalingAction.YES)

  # If swarming_stats is None, robocrop should use bot_fallback configs
  bot_policy_config = api.cros_infra_config.get_bot_policy_config()
  robocrop_swarming_action = api.bot_scaling.get_robocrop_action(
      bot_policy_config, api.bot_scaling.test_api.gce_provider_config(),
      swarming_stats=None)

  fallbacks = {
      policy.bot_group: policy.scaling_restriction.bot_fallback
      for policy in bot_policy_config.bot_policies
  }

  for action in robocrop_swarming_action.scaling_actions:
    api.assertions.assertEqual(action.bots_requested,
                               fallbacks[action.bot_group])

  # If bot_fallback is missing for a bot_group, there should not be a scaling
  # action for it but a warning step should be shown.
  missing_fallback_bot_policy_config = BotPolicyCfg.FromString(
      api.cros_infra_config.download_binproto(
          'configs/bot-scaling/generated/bot_policy',
          api.cros_infra_config.test_api.bot_policy_test_data_missing_fallback,
          repo='Chrome/config/repo'))

  robocrop_swarming_action = api.bot_scaling.get_robocrop_action(
      missing_fallback_bot_policy_config,
      api.bot_scaling.test_api.gce_provider_config(), swarming_stats=None)

  actions = {
      action.bot_group: action
      for action in robocrop_swarming_action.scaling_actions
  }

  for policy in missing_fallback_bot_policy_config.bot_policies:
    if not policy.scaling_restriction.bot_fallback:
      api.assertions.assertNotIn(policy.bot_group, actions.keys())
    else:
      api.assertions.assertEqual(policy.scaling_restriction.bot_fallback,
                                 actions[policy.bot_group].bots_requested)


def GenTests(api):
  yield api.test('basic')
