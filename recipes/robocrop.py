# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for scaling bots in Chrome and Chrome OS pools."""

from google.protobuf import json_format as jsonpb

from PB.recipes.chromeos.robocrop import RoboCropProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_scaling',
    'cros_infra_config',
    'easy',
    'swarming_cli',
]

PROPERTIES = RoboCropProperties

def RunSteps(api, properties):
  pools_to_monitor = properties.pools_to_monitor or ['cq', 'postsubmit']
  application = properties.application or 'ChromeOS'

  with api.step.nest('scale bot groups'):
    with api.step.nest('read bot policies'):
      bot_policy_config = api.cros_infra_config.get_bot_policy_config(
          application=application)
    with api.step.nest('get current GCE config') as pres:
      gce_config = api.bot_scaling.get_current_gce_config(bot_policy_config)
      pres.logs['gce_config'] = jsonpb.MessageToJson(gce_config)
    with api.step.nest('update bot policies') as pres:
      updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
          bot_policy_config, gce_config, application=application)
      reduced_bot_policy = api.bot_scaling.reduce_bot_policy_config_for_table(
          updated_bot_policy)
      api.easy.set_properties_step(
          bot_policy_config=jsonpb.MessageToDict(reduced_bot_policy))
      pres.logs['bot_policy_config'] = jsonpb.MessageToJson(updated_bot_policy)
    with api.step.nest('get current swarming stats') as pres:
      swarming_status = api.bot_scaling.get_swarming_stats(bot_policy_config)
      api.easy.set_properties_step(swarming_stats=swarming_status)
      pres.logs['swarming_stats'] = str(swarming_status)
    with api.step.nest('compute scaling actions') as pres:
      robocrop_action = api.bot_scaling.get_robocrop_action(
          updated_bot_policy, gce_config, swarming_stats=swarming_status)
      api.easy.set_properties_step(
          robocrop_action=jsonpb.MessageToDict(robocrop_action))
      pres.logs['robocrop_action'] = jsonpb.MessageToJson(robocrop_action)
    if properties.commit_changes:
      with api.step.nest('update GCE Provider configs') as pres:
        gce_updated_configs = api.bot_scaling.update_gce_configs(
            robocrop_action, gce_config)
        pres.logs['final_gce_config'] = jsonpb.MessageToJson(
            gce_updated_configs)


def GenTests(api):
  yield api.test('basic', api.properties(commit_changes=True))
  yield api.test('basic_chrome',
                 api.properties(commit_changes=True, application='Chrome'))
