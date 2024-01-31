# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.bot_scaling import BotPolicy

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
    'cros_infra_config',
]



def RunSteps(api):
  bot_policy_config = api.bot_scaling.test_api.robocrop_bot_policy_config()
  gce_config = api.bot_scaling.test_api.gce_provider_config()
  updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, gce_config)
  for policy in updated_bot_policy.bot_policies:
    api.assertions.assertEqual(policy.scaling_restriction.bot_ceiling, 150)
    api.assertions.assertEqual(policy.scaling_restriction.bot_floor, 20)

  bot_policy_config = api.bot_scaling.test_api.robocrop_bot_policy_config(
      policy_mode=BotPolicy.MONITORED)
  floor_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, gce_config)
  for policy in floor_bot_policy.bot_policies:
    api.assertions.assertEqual(policy.scaling_restriction.bot_ceiling, 150)
    api.assertions.assertEqual(policy.scaling_restriction.bot_floor, 25)

  reduced_config = api.bot_scaling.reduce_bot_policy_config_for_table(
      updated_bot_policy)
  api.assertions.assertEqual(reduced_config.bot_policies[0].bot_group, 'cq0')
  api.assertions.assertEqual(reduced_config.bot_policies[0].policy_mode, 2)


def GenTests(api):
  yield api.test('basic')
