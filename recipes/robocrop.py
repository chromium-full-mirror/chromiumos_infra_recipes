# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for scaling bots in the Chrome OS pool."""

from google.protobuf import json_format as jsonpb

from PB.recipes.chromeos.robocrop import RoboCropProperties

DEPS = [
    'recipe_engine/step',
    'bot_scaling',
    'buildbucket_stats',
    'cros_infra_config',
    'easy',
]

PROPERTIES = RoboCropProperties

def RunSteps(api, properties):
  pools_to_monitor = properties.pools_to_monitor or ['cq', 'postsubmit']

  with api.step.nest('monitor bot pools'):
    status_map = {}
    for pool in pools_to_monitor:
      status_map[pool] = api.buildbucket_stats.get_bucket_status(pool)

    # Save this data to output.properties.
    api.easy.set_property_step('current_bot_data', status_map)

  with api.step.nest('scale bot pools'):
    with api.step.nest('read bot policies'):
      bot_policy_config = api.cros_infra_config.get_bot_policy_config()
      api.easy.set_property_step('bot_policy_config',
                                 jsonpb.MessageToDict(bot_policy_config))
    with api.step.nest('compute scaling actions'):
      scaling_actions = []
      for policy in bot_policy_config.bot_policies:
        demand = api.buildbucket_stats.get_bot_demand(
            status_map[policy.bot_group])
        scaling_actions.append(
            api.bot_scaling.get_scaling_action(demand, policy))

      # TODO: Create a proto definition to clean up this step.
      actions_as_dict = [
          jsonpb.MessageToDict(action) for action in scaling_actions
      ]
      api.easy.set_property_step('robocrop_action', {
          'actionable': False,
          'scaling_actions': actions_as_dict,
      })


def GenTests(api):
  yield (api.test('basic'))
