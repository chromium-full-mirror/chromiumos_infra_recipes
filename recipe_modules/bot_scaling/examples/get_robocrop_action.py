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


def RunSteps(api):
  bot_policy_config = api.cros_infra_config.get_bot_policy_config()
  status_map = {'cq': {'STARTED': 23, 'SCHEDULED': 23}}

  robocrop_action = api.bot_scaling.get_robocrop_action(
      status_map, bot_policy_config,
      api.bot_scaling.test_api.gce_provider_config(), swarming_stats=None)
  api.assertions.assertEqual(len(robocrop_action.scaling_actions), 1)

  status_map = {'foo': {'STARTED': 23, 'SCHEDULED': 23}}
  robocrop_action = api.bot_scaling.get_robocrop_action(
      status_map, bot_policy_config,
      api.bot_scaling.test_api.gce_provider_config(), swarming_stats=None)
  api.assertions.assertEqual(len(robocrop_action.scaling_actions), 0)

  swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)
  robocrop_swarming_action = api.bot_scaling.get_robocrop_action(
      status_map, bot_policy_config,
      api.bot_scaling.test_api.gce_provider_config(),
      swarming_stats=swarming_stats)


def GenTests(api):
  yield (api.test('basic') + api.buildbucket.simulated_search_results(
      [api.bot_scaling.previous_robocrop()],
      'find matching builds.buildbucket.search'))
