# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for scaling bots in Chrome and ChromeOS pools."""

import dataclasses
import json
from typing import Dict, Generator, List, Optional, Set

from google.protobuf import json_format
from PB.recipes.chromeos import robocrop as robocrop_pb2
from PB.chromiumos import bot_scaling as bot_scaling_pb2
from PB.go.chromium.org.luci.gce.api.config.v1 import config as gce_config_pb2
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from RECIPE_MODULES.chromeos.bot_scaling import api as bot_scaling_api

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_scaling',
    'cros_infra_config',
    'easy',
    'deferrals',
]


PROPERTIES = robocrop_pb2.RoboCropProperties


def RunSteps(api: recipe_api.RecipeApi,
             properties: robocrop_pb2.RoboCropProperties) -> None:
  with api.deferrals.raise_exceptions_at_end():
    projects = get_robocrop_projects(properties)
    for project in projects:
      scale_bot_groups_for_project(api, project)


def get_robocrop_projects(
    properties: robocrop_pb2.RoboCropProperties
) -> List[robocrop_pb2.ProjectProperties]:
  """Find which projects this RoboCrop build should scale."""
  # TODO(b/329139593): Remove when RoboCropProperties are not directly used.
  # De-dupe projects to scale.
  found_applications: Set[str] = set()
  projects = []
  for project in properties.robocrop_projects:
    if project.application not in found_applications:
      projects.append(project)
      found_applications.add(project.application)
  main_application = properties.application or 'ChromeOS'
  if main_application not in found_applications:
    projects.append(
        robocrop_pb2.RoboCropProperties(
            commit_changes=properties.commit_changes,
            application=main_application))
  return projects


def scale_bot_groups_for_project(
    api: recipe_api.RecipeApi, project: robocrop_pb2.ProjectProperties) -> None:
  """Do all the bot scaling for a single RoboCrop project."""
  with api.step.nest(f'scale bot groups for {project.application}'):
    with api.step.nest('read bot policies'):
      bot_policy_config = api.cros_infra_config.get_bot_policy_config(
          application=project.application)
    gce_configs = get_gce_configs(api, bot_policy_config)
    updated_bot_policy = update_bot_policies(api, bot_policy_config,
                                             gce_configs)

    swarming_stats: Optional[bot_scaling_api.SwarmingStats] = None
    swarming_fetch_error: Optional[Exception] = None
    try:
      swarming_stats = get_current_swarming_stats(api, bot_policy_config)
    except api.step.InfraFailure as e:
      swarming_fetch_error = e
      with api.step.nest('Warning: using bot_fallback configs') as warning_step:
        warning_step.step_text = (
            'Using bot_fallback configs due to errors when fetching swarming stats'
        )
        warning_step.status = api.step.EXCEPTION

    robocrop_action = get_robocrop_action(api, updated_bot_policy, gce_configs,
                                          swarming_stats)
    execute_robocrop_action(api, project, robocrop_action, gce_configs)

    if swarming_fetch_error is not None:
      raise swarming_fetch_error


def get_gce_configs(
    api: recipe_api.RecipeApi,
    bot_policy_config: bot_scaling_pb2.BotPolicyCfg) -> gce_config_pb2.Configs:
  """Return the current GCE configs from gce_provider."""
  with api.step.nest('get current GCE config') as pres:
    response = api.bot_scaling.get_current_gce_config(bot_policy_config)
    gce_configs = response.configs
    pres.logs['gce_config'] = json_format.MessageToJson(gce_configs)
    if response.missing_configs:
      pres.status = api.step.FAILURE
      missing_cfgs = ','.join(response.missing_configs)
      pres.step_summary_text = f'No config found for prefix(s): {missing_cfgs}'
  return gce_configs


def update_bot_policies(
    api: recipe_api.RecipeApi, bot_policy_config: bot_scaling_pb2.BotPolicyCfg,
    gce_configs: gce_config_pb2.Configs) -> bot_scaling_pb2.BotPolicyCfg:
  """Update the bot policy configs to reflect ScalingRestriction values."""
  with api.step.nest('update bot policies') as pres:
    updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
        bot_policy_config, gce_configs)
    reduced_bot_policy = api.bot_scaling.reduce_bot_policy_config_for_table(
        updated_bot_policy)
    api.easy.set_properties_step(
        bot_policy_config=json_format.MessageToDict(reduced_bot_policy))
    pres.logs['bot_policy_config'] = json_format.MessageToJson(
        updated_bot_policy)
  return updated_bot_policy


def get_current_swarming_stats(
    api: recipe_api.RecipeApi, bot_policy_config: bot_scaling_pb2.BotPolicyCfg
) -> bot_scaling_api.SwarmingStats:
  """Query Swarming for the current bot and task stats."""
  with api.step.nest('get current swarming stats') as pres:
    swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)
    api.easy.set_properties_step(
        swarming_stats=dataclasses.astuple(swarming_stats))
    pres.logs['swarming_stats'] = str(swarming_stats)
  return swarming_stats


def get_robocrop_action(
    api: recipe_api.RecipeApi, bot_policy: bot_scaling_pb2.BotPolicyCfg,
    gce_configs: gce_config_pb2.Configs,
    swarming_stats: bot_scaling_api.SwarmingStats
) -> bot_scaling_pb2.RoboCropAction:
  """Determine the comprehensive scaling actions to take."""
  with api.step.nest('compute scaling actions') as pres:
    robocrop_action = api.bot_scaling.get_robocrop_action(
        bot_policy, gce_configs, swarming_stats=swarming_stats)
    api.easy.set_properties_step(
        robocrop_action=json_format.MessageToDict(robocrop_action))
    pres.logs['robocrop_action'] = json_format.MessageToJson(robocrop_action)
  return robocrop_action


def execute_robocrop_action(
    api: recipe_api.RecipeApi, project: robocrop_pb2.ProjectProperties,
    action: bot_scaling_pb2.RoboCropAction,
    original_gce_configs: gce_config_pb2.Configs) -> None:
  """Execute the given RoboCropAction on the given project."""
  if project.commit_changes:
    step_name = 'update GCE Provider configs'
  else:
    step_name = 'no change to GCE Provider configs'

  with api.step.nest(step_name) as pres:
    if project.commit_changes:
      updated_gce_configs = api.bot_scaling.update_gce_configs(
          action, original_gce_configs)
    else:
      updated_gce_configs = original_gce_configs  # NO-OP
    pres.logs['final_gce_config'] = json_format.MessageToJson(
        updated_gce_configs)

    delta_by_prefix = get_delta_gce_configs(original_gce_configs,
                                            updated_gce_configs)
    pres.logs['delta_gce_config'] = json.dumps(delta_by_prefix,
                                               separators=(',', ':'), indent=2,
                                               sort_keys=True)


def get_delta_gce_configs(
    original_gce_configs: gce_config_pb2.Configs,
    updated_gce_configs: gce_config_pb2.Configs) -> Dict[str, str]:
  """Calculate how much each VM group was changed by.

  Args:
    original_gce_configs: The gce_configs before this build.
    updated_gce_configs: The gce_configs resulting from this build.

  Returns:
    A dict of {prefix: delta}, where "prefix" is a VM config's prefix, and
    "delta" is a descriptive string of how that VM's current_amount changed.
  """
  delta_by_prefix = {}
  for updated in updated_gce_configs.vms:
    for original in original_gce_configs.vms:
      if original.prefix == updated.prefix:
        before = original.current_amount
        after = updated.current_amount
        difference = after - before
        delta_by_prefix[updated.prefix] = f'{before} -> {after}: {difference}'
  return delta_by_prefix


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
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
          robocrop_pb2.RoboCropProperties(robocrop_projects=[
              robocrop_pb2.ProjectProperties(application='ChromeOSMPA',
                                             commit_changes=True)
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
          robocrop_pb2.RoboCropProperties(robocrop_projects=[
              robocrop_pb2.ProjectProperties(application='ChromeOSMPA',
                                             commit_changes=True),
              robocrop_pb2.ProjectProperties(application='ChromeOS',
                                             commit_changes=True)
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
