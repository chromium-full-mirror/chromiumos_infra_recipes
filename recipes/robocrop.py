# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for scaling bots in the Chrome OS pool."""

from google.protobuf import json_format as jsonpb

from PB.recipes.chromeos.robocrop import RoboCropProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_scaling',
    'buildbucket_stats',
    'cros_infra_config',
    'easy',
    'swarming_cli',
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

  with api.step.nest('scale bot groups'):
    with api.step.nest('read bot policies'):
      bot_policy_config = api.cros_infra_config.get_bot_policy_config()
    with api.step.nest('get current GCE config') as step:
      gce_config = api.bot_scaling.get_current_gce_config(bot_policy_config)
      api.easy.set_property_step('gce_config', jsonpb.MessageToDict(gce_config))
    with api.step.nest('update bot policies') as step:
      updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
          bot_policy_config, gce_config)
      api.easy.set_property_step('bot_policy_config',
                                 jsonpb.MessageToDict(updated_bot_policy))
    with api.step.nest('get current swarming stats') as step:
      swarming_counts = api.bot_scaling.get_swarming_stats(bot_policy_config)
      api.easy.set_property_step('swarming_stats', swarming_counts)
    with api.step.nest('compute buildbucket based scaling actions'):
      robocrop_alt_action = api.bot_scaling.get_robocrop_action(
          status_map, updated_bot_policy, gce_config, swarming_stats=None)
      api.easy.set_property_step('robocrop_buildbucket_action',
                                 jsonpb.MessageToDict(robocrop_alt_action))
    with api.step.nest('compute scaling actions'):
      robocrop_action = api.bot_scaling.get_robocrop_action(
          status_map, updated_bot_policy, gce_config,
          swarming_stats=swarming_counts)
      api.easy.set_property_step('robocrop_action',
                                 jsonpb.MessageToDict(robocrop_action))
    if properties.commit_changes:
      with api.step.nest('update GCE Provider configs'):
        gce_updated_configs = api.bot_scaling.update_gce_configs(
            robocrop_action, gce_config)
        api.easy.set_property_step('final_gce_config',
                                   jsonpb.MessageToDict(gce_updated_configs))


def GenTests(api):
  yield (api.test('basic') + #
       api.properties(commit_changes=True) + #
       api.buildbucket.simulated_search_results(
      [api.bot_scaling.previous_robocrop()],
      'scale bot groups.compute scaling actions.'
      'find matching builds.buildbucket.search'))
