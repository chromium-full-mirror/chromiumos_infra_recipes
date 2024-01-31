# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for scaling bots in Chrome and CrOS pools."""

import dataclasses
import json

from google.protobuf import json_format as jsonpb

from PB.recipes.chromeos.robocrop import RoboCropProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_scaling',
    'cros_infra_config',
    'easy',
    'deferrals',
]


PROPERTIES = RoboCropProperties


def RunSteps(api: RecipeApi, properties: RoboCropProperties):
  application = properties.application or 'ChromeOS'

  with api.deferrals.raise_exceptions_at_end(), api.step.nest(
      'scale bot groups'):
    with api.step.nest('read bot policies'):
      bot_policy_config = api.cros_infra_config.get_bot_policy_config(
          application=application)
    with api.step.nest('get current GCE config') as pres:
      gce_config_tuple = api.bot_scaling.get_current_gce_config(
          bot_policy_config)
      gce_config = gce_config_tuple.configs
      pres.logs['gce_config'] = jsonpb.MessageToJson(gce_config)
      if gce_config_tuple.missing_configs:
        pres.status = api.step.FAILURE
        pres.step_summary_text = 'No config found for prefix(s): {}'.format(
            ','.join(gce_config_tuple.missing_configs))
    with api.step.nest('update bot policies') as pres:
      updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
          bot_policy_config, gce_config)
      reduced_bot_policy = api.bot_scaling.reduce_bot_policy_config_for_table(
          updated_bot_policy)
      api.easy.set_properties_step(
          bot_policy_config=jsonpb.MessageToDict(reduced_bot_policy))
      pres.logs['bot_policy_config'] = jsonpb.MessageToJson(updated_bot_policy)

    has_swarming_fetch_error = False
    try:
      with api.step.nest('get current swarming stats') as pres:
        swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)
        api.easy.set_properties_step(
            swarming_stats=dataclasses.astuple(swarming_stats))
        pres.logs['swarming_stats'] = str(swarming_stats)
    except api.step.InfraFailure as e:
      has_swarming_fetch_error = True
      swarming_fetch_error = e
      swarming_stats = None

      warning_step = api.step('Warning: using bot_fallback configs', [])
      warning_step.presentation.step_text = ('Using bot_fallback configs due to'
                                             ' errors when fetching swarming'
                                             ' stats')
      warning_step.presentation.status = api.step.EXCEPTION

    with api.step.nest('compute scaling actions') as pres:
      robocrop_action = api.bot_scaling.get_robocrop_action(
          updated_bot_policy, gce_config, swarming_stats=swarming_stats)

      api.easy.set_properties_step(
          robocrop_action=jsonpb.MessageToDict(robocrop_action))

      pres.logs['robocrop_action'] = jsonpb.MessageToJson(robocrop_action)

    action = 'update' if properties.commit_changes else 'no change to'
    with api.step.nest('{} GCE Provider configs'.format(action)) as pres:
      if properties.commit_changes:
        gce_updated_configs = api.bot_scaling.update_gce_configs(
            robocrop_action, gce_config)
      else:
        gce_updated_configs = gce_config  # NO-OP

      pres.logs['final_gce_config'] = jsonpb.MessageToJson(gce_updated_configs)

      delta = {}
      for updated in gce_updated_configs.vms:
        for current in gce_config.vms:
          if current.prefix == updated.prefix:
            delta[updated.prefix] = '{before} -> {after}: {delta}'.format(
                before=current.current_amount, after=updated.current_amount,
                delta=updated.current_amount - current.current_amount)
      pres.logs['delta_gce_config'] = json.dumps(delta, separators=(',', ':'),
                                                 indent=2, sort_keys=True)

    if has_swarming_fetch_error:
      raise swarming_fetch_error  # pylint: disable=used-before-assignment


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(commit_changes=True),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
  yield api.test(
      'no-commit-changes',
      api.properties(commit_changes=False),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
  yield api.test('basic-chrome',
                 api.properties(commit_changes=True, application='Chrome'))
  yield api.test(
      'bot-fallbacks',
      api.properties(commit_changes=True),
      api.override_step_data(
          'scale bot groups.get current swarming stats.get bot count query result',
          retcode=1),
      api.post_check(
          post_process.MustRun,
          'scale bot groups.Warning: using bot_fallback configs',
          'scale bot groups.compute scaling actions',
          'scale bot groups.update GCE Provider configs',
      ),
      status='INFRA_FAILURE',
  )
