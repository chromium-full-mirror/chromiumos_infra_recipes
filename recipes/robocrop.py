# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for scaling bots in Chrome and CrOS pools."""

import dataclasses
import json

from google.protobuf import json_format as jsonpb

from PB.recipes.chromeos.robocrop import RoboCropProperties, ProjectProperties
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
  with api.deferrals.raise_exceptions_at_end():
    # TODO(b/329139593): Remove when RoboCropProperties are not directly used.
    # De-dupe projects to scale.
    configured_apps = set()
    projects = []
    for project in list(properties.robocrop_projects):
      if project.application not in configured_apps:
        projects.append(project)
        configured_apps.add(project.application)
    application = properties.application or 'ChromeOS'
    if application not in configured_apps:
      projects.append(
          RoboCropProperties(commit_changes=properties.commit_changes,
                             application=application))
    for robocrop_project in projects:
      application = robocrop_project.application
      with api.step.nest(f'scale bot groups for {application}') as pres:
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
          pres.logs['bot_policy_config'] = jsonpb.MessageToJson(
              updated_bot_policy)

        has_swarming_fetch_error = False
        try:
          with api.step.nest('get current swarming stats') as pres:
            swarming_stats = api.bot_scaling.get_swarming_stats(
                bot_policy_config)
            api.easy.set_properties_step(
                swarming_stats=dataclasses.astuple(swarming_stats))
            pres.logs['swarming_stats'] = str(swarming_stats)
        except api.step.InfraFailure as e:
          has_swarming_fetch_error = True
          swarming_fetch_error = e
          swarming_stats = None

          warning_step = api.step('Warning: using bot_fallback configs', [])
          warning_step.presentation.step_text = (
              'Using bot_fallback configs due to'
              ' errors when fetching swarming'
              ' stats')
          warning_step.presentation.status = api.step.EXCEPTION

        with api.step.nest('compute scaling actions') as pres:
          robocrop_action = api.bot_scaling.get_robocrop_action(
              updated_bot_policy, gce_config, swarming_stats=swarming_stats)

          api.easy.set_properties_step(
              robocrop_action=jsonpb.MessageToDict(robocrop_action))

          pres.logs['robocrop_action'] = jsonpb.MessageToJson(robocrop_action)

        action = 'update' if robocrop_project.commit_changes else 'no change to'
        with api.step.nest('{} GCE Provider configs'.format(action)) as pres:
          if robocrop_project.commit_changes:
            gce_updated_configs = api.bot_scaling.update_gce_configs(
                robocrop_action, gce_config)
          else:
            gce_updated_configs = gce_config  # NO-OP

          pres.logs['final_gce_config'] = jsonpb.MessageToJson(
              gce_updated_configs)

          delta = {}
          for updated in gce_updated_configs.vms:
            for current in gce_config.vms:
              if current.prefix == updated.prefix:
                delta[updated.prefix] = '{before} -> {after}: {delta}'.format(
                    before=current.current_amount, after=updated.current_amount,
                    delta=updated.current_amount - current.current_amount)
          pres.logs['delta_gce_config'] = json.dumps(delta,
                                                     separators=(',', ':'),
                                                     indent=2, sort_keys=True)

        if has_swarming_fetch_error:
          raise swarming_fetch_error  # pylint: disable=used-before-assignment


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(commit_changes=True),
      # Test ultimately fails due to prefix-fifth not being found, but failure should not affect other behavior.
      status='FAILURE',
  )
  yield api.test(
      'no-commit-changes',
      api.properties(commit_changes=False),
      # Test ultimately fails due to prefix-fifth not being found, but failure should not affect other behavior.
      status='FAILURE',
  )
  yield api.test('basic-chrome',
                 api.properties(commit_changes=True, application='Chrome'))
  yield api.test(
      'bot-fallbacks',
      api.properties(commit_changes=True),
      api.override_step_data(
          'scale bot groups for ChromeOS.get current swarming stats.get bot count query result for cq',
          retcode=1),
      api.post_check(
          post_process.MustRun,
          'scale bot groups for ChromeOS.Warning: using bot_fallback configs',
          'scale bot groups for ChromeOS.compute scaling actions',
          'scale bot groups for ChromeOS.update GCE Provider configs',
      ),
      status='INFRA_FAILURE',
  )
  yield api.test(
      'multiple-applications',
      api.properties(
          RoboCropProperties(robocrop_projects=[
              ProjectProperties(application='ChromeOSMPA', commit_changes=True)
          ])),
      api.post_check(
          post_process.MustRun,
          'scale bot groups for ChromeOS',
          'scale bot groups for ChromeOSMPA',
      ),
      # Test ultimately fails due to prefix-fifth not being found, but failure should not affect other behavior.
      status='FAILURE',
  )
  # TODO(b/329139593): Remove when RoboCropProperties are not directly used and we don't need to dedupe.
  # Application defaults to ChromeOS, but don't scale twice.
  yield api.test(
      'multiple-applications-deduped',
      api.properties(
          RoboCropProperties(robocrop_projects=[
              ProjectProperties(application='ChromeOSMPA', commit_changes=True),
              ProjectProperties(application='ChromeOS', commit_changes=True)
          ])),
      api.post_check(
          post_process.MustRun,
          'scale bot groups for ChromeOS',
          'scale bot groups for ChromeOS.update GCE Provider configs',
          'scale bot groups for ChromeOSMPA',
          'scale bot groups for ChromeOSMPA.update GCE Provider configs',
      ),
      api.post_check(
          post_process.DoesNotRun,
          'scale bot groups for ChromeOS (2)',
      ),
      # Test ultimately fails due to prefix-fifth not being found, but failure should not affect other behavior.
      status='FAILURE',
  )
