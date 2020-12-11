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

from PB.chromiumos.bot_scaling import ScalingAction


def RunSteps(api):
  bot_policy_config = api.cros_infra_config.get_bot_policy_config()
  swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)
  robocrop_swarming_action = api.bot_scaling.get_robocrop_action(
      bot_policy_config, api.bot_scaling.test_api.gce_provider_config(),
      swarming_stats=swarming_stats)
  for action in robocrop_swarming_action.scaling_actions:
    api.assertions.assertEqual(action.actionable, ScalingAction.YES)


def GenTests(api):
  yield api.test('basic')
