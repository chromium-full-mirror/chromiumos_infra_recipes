# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from collections import namedtuple

from PB.chromiumos.bot_scaling import ApplicationUtilization, BotPolicy, ResourceUtilization, RoboCropAction, ScalingAction
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.gce.api.config.v1.config import Config, Configs

from google.protobuf import field_mask_pb2
from google.protobuf import json_format as jsonpb
from recipe_engine import recipe_api

import itertools

TASK_STATES = ['RUNNING', 'PENDING']
EXECUTION_HOUR_PERCENTILE = .16

BotStats = namedtuple('BotStats', [
    'bot_group', 'busy', 'count', 'dead', 'maintenance', 'quarantined', 'min',
    'max'
])
TaskStats = namedtuple('TaskStats', ['bot_group', 'task_state', 'count'])
SwarmingStats = namedtuple('SwarmingStats', ['bot_stats', 'task_stats'])


class BotScalingApi(recipe_api.RecipeApi):
  """A module that determines how to scale bot groups."""

  def get_robocrop_action(self, bot_policy_config, configs, swarming_stats):
    """Function to compute all the actions of this RoboCrop.

    Args:
      bot_policy_config(BotPolicyCfg): Config define Policy for
        the RoboCrop.
      configs(Configs): List of GCE Config objects.
      swarming_stats(SwarmingStats): Named tuple containing current
        Swarming bot and task counts.

    Returns:
      ScalingAction, comprehensive action to be taken by RoboCrop.
    """
    scaling_actions = []
    for policy in bot_policy_config.bot_policies:
      demand = self.get_swarming_demand(swarming_stats, policy.bot_group)
      scaling_actions.append(self.get_scaling_action(demand, policy, configs))

    quota_usage = self._get_quota_usage(scaling_actions, configs)

    return RoboCropAction(scaling_actions=scaling_actions,
                          appl_resource_utilization=quota_usage)

  def get_scaling_action(self, demand, bot_policy, configs):
    """The function that creates a ScalingAction for a bot group.

    Args:
      demand(int): Current demand for bots.
      bot_policy(BotPolicy): Config defined Policy for a bot group.
      configs(Configs): List of GCE Config objects.

    Returns:
      ScalingAction, comprehensive action to be taken by RoboCrop.
    """
    bots_requested = self.get_bot_request(demand,
                                          bot_policy.scaling_restriction)
    bots_configured = self.get_gce_bots_configured(
        bot_policy.region_restrictions, self._get_prefix_to_gce_config(configs))
    actionable = ScalingAction.NO

    # Check to determine whether bots should be scaled up or down.
    # Calculation based on weights can leave a bot group a few bots short,
    # thus we provide a small allowance when determining actionable.
    if (bots_configured > bot_policy.scaling_restriction.bot_ceiling or
        bots_configured + bot_policy.scaling_restriction.step_size <=
        bots_requested or
        bots_configured - bot_policy.scaling_restriction.step_size >=
        bots_requested or
        (bots_requested == bot_policy.scaling_restriction.bot_ceiling and
         abs(bots_requested - bots_configured) > 2)):
      actionable = ScalingAction.YES

    # Check whether a bot policy is set as configured, otherwise set to NO.
    if bot_policy.policy_mode != BotPolicy.CONFIGURED:
      actionable = ScalingAction.NO

    scaling_action = ScalingAction(
        bot_group=bot_policy.bot_group, bot_type=bot_policy.bot_type,
        actionable=actionable, bot_min=bot_policy.scaling_restriction.bot_floor,
        bot_max=bot_policy.scaling_restriction.bot_ceiling,
        application=bot_policy.application)

    scaling_action.bots_requested = self._calculate_bot_adjustment(
        bot_policy, bots_requested, bots_configured)
    scaling_action.estimated_savings = self._calculate_estimated_savings(
        bot_policy, scaling_action.bots_requested, bots_configured, actionable)
    scaling_action.regional_actions.extend(
        self.get_regional_actions(scaling_action.bots_requested,
                                  bot_policy.region_restrictions))
    return scaling_action

  def get_bot_request(self, demand, scaling_restriction):
    """Core function that scales bots based on demand.

    Args:
      demand(int): Current demand for bots.
      scaling_restriction(ScalingRestriction): Scaling restriction defined by
        the bot policy.

    Returns:
      int, number of bots to request.
    """
    bot_ceiling = scaling_restriction.bot_ceiling
    bot_floor = scaling_restriction.bot_floor
    min_idle = scaling_restriction.min_idle
    bot_request = max(demand + min_idle, bot_floor)
    bot_request = min(bot_request, bot_ceiling)
    return bot_request

  def get_regional_actions(self, bots_requested, region_restrictions):
    """Determines regional distribution of bot requests.

    Args:
      bots_requested(int): Total number of bots requested.
      region_restrictions(list[RegionRestriction]): Regional preferences
        from config.

    Returns:
      list[RegionalAction], region wise distribution of bots requested.
    """
    # TODO(dhanyaganesh): Make this function aware of budgets.
    total_weight = sum(
        [restriction.weight for restriction in region_restrictions])
    actions = [
        ScalingAction.RegionalAction(
            region=restriction.region,
            prefix=restriction.prefix,
            bots_requested=int(
                round(restriction.weight * bots_requested / total_weight)),
        ) for restriction in region_restrictions
    ]
    return actions

  def get_swarming_demand(self, swarming_stats, bot_group):
    """Return the demand for bots in a bot group.

    Args:
      swarming_stats(SwarmingStats): Named tuple containing bot and task
        Swarming stats.
      bot_group (str): Name of bot group

    Returns:
      int, the current demand for bots in the group.
    """
    demand = 0
    for stat in swarming_stats.task_stats:
      if stat.bot_group == bot_group:
        if stat.task_state in TASK_STATES:
          demand += int(stat.count)

    return demand

  def get_swarming_stats(self, bot_policy_config):
    """Determines the current Swarming stats per bot group.

    Args:
      bot_policy_config(BotPolicyCfg): Config define Policy for
        the RoboCrop.

    Returns:
      SwarmingStats:  bot and task stats named tuple.
    """
    bot_stats = []
    task_stats = []
    for policy in bot_policy_config.bot_policies:
      dimensions = self.unpack_policy_dimensions(policy.swarming_dimensions)
      bot_stats_hold = []
      task_stats_hold = []
      for dim in dimensions:
        # Bot counts get duplicated, due to the way dimensions are associated,
        # therefore we only need to count the first returned count.
        if not bot_stats_hold:
          bot_stats_hold = self._bot_swarming_stats(
              policy.bot_group,
              self.m.swarming_cli.get_bot_counts(policy.swarming_instance, dim),
              policy.scaling_restriction.bot_floor,
              policy.scaling_restriction.bot_ceiling)
        for state in TASK_STATES:
          task_stats_hold = self._task_swarming_stats(
              policy.bot_group, state, task_stats_hold,
              self.m.swarming_cli.get_task_counts(dim, state,
                                                  policy.lookback_hours,
                                                  policy.swarming_instance))
      bot_stats.append(bot_stats_hold)
      task_stats.extend(task_stats_hold)
    return SwarmingStats(bot_stats, task_stats)

  def get_current_gce_config(self, bot_policy_config):
    """Retrieves the current configuration from GCE Provider service.

    Args:
      bot_policy_config(BotPolicyCfg): Config define Policy for
        the RoboCrop.

    Returns:
      list(Config), GCE Provider config definitions.
    """
    prefixes = []
    for policy in bot_policy_config.bot_policies:
      for restriction in policy.region_restrictions:
        prefixes.append(restriction.prefix)
    return self.m.gce_provider.get_current_config(prefixes)

  def get_gce_bots_configured(self, region_restrictions, config_map):
    """Sums the total number of configured bots per bot policy.

    Args:
      region_restrictions(list[RegionRestriction]): Regional preferences
        from config.
      config_map(dict|Config): Map of GCE Config to prefix

    Returns:
      int, sum of the total number of bots in GCE Provider
    """
    policy_count = 0
    for restriction in region_restrictions:
      config = config_map.get(restriction.prefix, Config())
      policy_count += config.current_amount
    return policy_count

  def update_bot_policy_limits(self, bot_policy_config, configs):
    """Sums the min and max bot numbers per bot policy.

    Args:
      bot_policy_config(BotPolicyCfg): Config define Policy for
        the RoboCrop.
      config_map(dict|Config): Map of GCE Config to prefix

    Returns:
      BotPolicy, updated to reflect ScalingRestriction values.
    """
    config_map = self._get_prefix_to_gce_config(configs)
    for policy in bot_policy_config.bot_policies:
      policy.scaling_restriction.bot_ceiling = 0
      policy.scaling_restriction.bot_floor = 0
      for restriction in policy.region_restrictions:
        config = config_map.get(restriction.prefix, Config())
        policy.scaling_restriction.bot_ceiling += config.amount.max
        policy.scaling_restriction.bot_floor += config.amount.min
      if policy.policy_mode == BotPolicy.MONITORED:
        policy.scaling_restriction.bot_floor = policy.scaling_restriction.min_idle
    return bot_policy_config

  def update_gce_configs(self, robocrop_actions, configs):
    """Updates each GCE Provider config that is actionable.

    Args:
      robocrop_actions(list[ScalingAction]): Repeatable ScalingAction
        configs to update.
      configs(Configs): List of GCE Config objects.

    Returns:
      list(Config), GCE Provider config definitions.
    """
    gce_configs = []
    gce_map = self._get_prefix_to_gce_config(configs)
    for scaling_action in robocrop_actions.scaling_actions:
      if scaling_action.actionable == ScalingAction.YES:
        for action in scaling_action.regional_actions:
          config = gce_map.get(action.prefix, None)
          if config is not None:
            config.current_amount = action.bots_requested
            gce_configs.append(
                self.m.gce_provider.update_gce_config(action.prefix, config))
    return Configs(vms=gce_configs)

  def unpack_policy_dimensions(self, dimensions):
    """Method to iterate through dimensions and return possible combinations.

    Args:
      dimensions (list[dict]): BotPolicy swarming dimensions.

    Returns:
      list, product of all swarming dimensions for querying.
    """
    policy_dimensions = []
    dims = {d.name: d.values for d in dimensions}
    for name, value in dims.items():
      temp_dimensions = []
      for val in value:
        temp_dimensions.append('{}:{}'.format(name, val))
      policy_dimensions.append(temp_dimensions)
    return list(itertools.product(*policy_dimensions))

  def _get_quota_usage(self, scaling_actions, configs):
    """Method to calculate quota usage based on scaling actions.

    Args:
      robocrop_actions(list[ScalingAction]): Repeatable ScalingAction
        configs.
      configs(Configs): List of GCE Config objects.
    Returns:
      ResourceUtilization, total resource usage across all bot groups.
    """
    config_map = self._get_prefix_to_gce_config(configs)
    appl_resource_utilization = {}
    for action in scaling_actions:
      resource_utilization = {}
      global_usage = ResourceUtilization(region='global', vms=0, cpus=0,
                                         memory_gb=0, disk_gb=0, max_cpus=0)
      if action.application in appl_resource_utilization:
        appl_util = appl_resource_utilization[action.application]
      else:
        appl_util = appl_resource_utilization.get(
            action.application,
            ApplicationUtilization(application=action.application,
                                   resource_utilization=[global_usage]))
      for ru in appl_util.resource_utilization:
        resource_utilization[ru.region] = ru
      global_usage = resource_utilization.get(
          'global',
          ResourceUtilization(region='global', vms=0, cpus=0, memory_gb=0,
                              disk_gb=0, max_cpus=0))
      for regional_action in action.regional_actions:
        config = config_map.get(regional_action.prefix, None)
        if config:
          usage = resource_utilization.get(
              regional_action.region,
              ResourceUtilization(region=regional_action.region, vms=0, cpus=0,
                                  memory_gb=0, disk_gb=0, max_cpus=0))
          if action.actionable == ScalingAction.NO:
            usage.vms += config.current_amount
            usage.memory_gb += config.current_amount * action.bot_type.memory_gb
            usage.cpus += config.current_amount * action.bot_type.cores_per_bot
            for disk in config.attributes.disk:
              usage.disk_gb += config.current_amount * disk.size
            global_usage.vms += config.current_amount
            global_usage.cpus += config.current_amount * action.bot_type.cores_per_bot
            global_usage.memory_gb += round(config.current_amount *
                                            action.bot_type.memory_gb)
            for disk in config.attributes.disk:
              global_usage.disk_gb += config.current_amount * disk.size
            global_usage.max_cpus += config.amount.max * action.bot_type.cores_per_bot
          elif action.actionable == ScalingAction.YES:
            usage.vms += regional_action.bots_requested
            usage.memory_gb += round(regional_action.bots_requested *
                                     action.bot_type.memory_gb)
            usage.cpus += regional_action.bots_requested * action.bot_type.cores_per_bot
            for disk in config.attributes.disk:
              usage.disk_gb += regional_action.bots_requested * disk.size
            usage.max_cpus += config.amount.max * action.bot_type.cores_per_bot
          resource_utilization[regional_action.region] = usage
      if action.actionable == ScalingAction.YES:
        global_usage.vms += action.bots_requested
        global_usage.cpus += action.bots_requested * action.bot_type.cores_per_bot
        global_usage.memory_gb += round(action.bots_requested *
                                        action.bot_type.memory_gb)
        for disk in config.attributes.disk:
          global_usage.disk_gb += action.bots_requested * disk.size
      resource_utilization['global'] = global_usage
      appl_resource_utilization[action.application] = ApplicationUtilization(
          application=action.application,
          resource_utilization=resource_utilization.values())
    return appl_resource_utilization.values()

  def _get_prefix_to_gce_config(self, configs):
    """Helper method that returns the prefix to Config map.

    Loads the proto and builds the map.

    Args:
      configs (Configs): list of GCE Provider Config meessages.

    Returns:
      dict, map of prefix to GCE Config
    """
    return {c.prefix: c for c in configs.vms}

  def _bot_swarming_stats(self, bot_group, cli_stats, min, max):
    """Helper method that formats the bot stats into a named tuple.

    Args:
      bot_group (str): name of bot group associated with stats.
      cli_stats (dict): swarming CLI dict of bot stats.
      min (int): bot floor from config
      max (int): bot ceiling from config

    Returns:
      BotStats: Swarming bot stats named tuple.
    """
    return BotStats(bot_group, int(cli_stats.get('busy', 0)),
                    int(cli_stats.get('count', 0)),
                    int(cli_stats.get('dead', 0)),
                    int(cli_stats.get('maintenance', 0)),
                    int(cli_stats.get('quarantined', 0)), min, max)

  def _task_swarming_stats(self, bot_group, state, task_stats, cli_stats):
    """Helper method that formats the bot stats into a named tuple.

    Args:
      bot_group (str): name of bot group associated with stats.
      state (str): Swarming task state.
      task_stats (TaskStats): current value of accumulated task stats.
      cli_stats (dict): swarming CL dict of task stats.

    Returns:
      TaskStats: Swarming task stats named tuple.
    """
    new_task = True
    updated_stats = []
    for stat in task_stats:
      if stat.bot_group == bot_group and stat.task_state == state:
        updated_stats.append(
            TaskStats(bot_group, state,
                      int(stat.count) + int(cli_stats.get('count', 0))))
        new_task = False
      else:
        updated_stats.append(stat)
    if new_task:
      updated_stats.append(
          TaskStats(bot_group, state, int(cli_stats.get('count', 0))))
    return updated_stats

  def _calculate_bot_adjustment(self, bot_policy, requested, current_amount):
    """Helper to calculate the number of bots to request.

    Args:
      bot_policy_config(BotPolicy): Group Policy for RoboCrop.
      requested (int): number of bots needed.
      curent_amount (int): current number of bots configured.

    Returns:
      int, the number of bots to request.
    """
    bots_requested = 0
    if bot_policy.scaling_mode == BotPolicy.STEPPED:
      if requested >= current_amount:
        bots_requested = current_amount + min(
            (requested - current_amount),
            bot_policy.scaling_restriction.step_size)
      else:
        bots_requested = current_amount - min(
            (current_amount - bots_requested),
            bot_policy.scaling_restriction.step_size)
    else:
      bots_requested = requested
    return bots_requested

  def _calculate_estimated_savings(self, bot_policy, requested, configured,
                                   actionable):
    """Helper to calculate the estimated cost savings per bot group.

    Args:
      bot_policy_config(BotPolicy): Group Policy for RoboCrop.
      requested (int): number of bots needed.
      configured (int): current number of bots configured.
      actionable (ScalingAction): enum whether to take action.

    Returns:
      float, the estimated bot group savings per execution.
    """
    bot_base = configured if (actionable == ScalingAction.NO) else requested
    return (bot_policy.scaling_restriction.bot_ceiling - bot_base) * (
        bot_policy.bot_type.hourly_cost * EXECUTION_HOUR_PERCENTILE)
