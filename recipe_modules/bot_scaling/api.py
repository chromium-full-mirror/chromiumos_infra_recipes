# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from collections import namedtuple

from PB.chromiumos.bot_scaling import (ApplicationUtilization, BotPolicy,
                                       ReducedBotPolicyCfg, ResourceUtilization,
                                       RoboCropAction, ScalingAction)
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.gce.api.config.v1.config import Config, Configs

from google.protobuf import json_format as jsonpb
from google.protobuf import timestamp_pb2
from recipe_engine import recipe_api

import decimal
import itertools

DEFAULT_HOURS_BETWEEN_BUILDS = 0.167
TASK_STATES = ['RUNNING', 'PENDING']

BotStats = namedtuple('BotStats', [
    'bot_group', 'busy', 'count', 'dead', 'maintenance', 'quarantined', 'min',
    'max'
])
TaskStats = namedtuple('TaskStats', ['bot_group', 'task_state', 'count'])
SwarmingStats = namedtuple('SwarmingStats', ['bot_stats', 'task_stats'])


class BotScalingApi(recipe_api.RecipeApi):
  """A module that determines how to scale bot groups."""

  def __init__(self, *args, **kwargs):
    super(BotScalingApi, self).__init__(*args, **kwargs)
    self._hours_between_builds = None

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
    missing_bot_fallbacks = []
    for policy in bot_policy_config.bot_policies:
      # swarming_stats will be None when if there were errors fetching them
      # In this case, set bots to bot_fallback configs
      if swarming_stats is None:
        # There should never be bot_policy configs with missing bot_fallback
        # configs or bot_fallbacks set to 0, so just skip over those and make
        # the step red.
        if policy.scaling_restriction.bot_fallback:
          demand = policy.scaling_restriction.bot_fallback
          scaling_actions.append(
              self.get_scaling_action(demand, policy, configs))
        else:
          missing_bot_fallbacks.append(policy.bot_group)
      else:
        demand = self.get_swarming_demand(swarming_stats, policy.bot_group)
        scaling_actions.append(self.get_scaling_action(demand, policy, configs))
    if missing_bot_fallbacks:
      step = self.m.step.active_result
      step.presentation.logs['missing_bot_fallbacks'] = self.m.json.dumps(
          missing_bot_fallbacks)
      step.presentation.status = self.m.step.EXCEPTION

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
        bots_requested != bots_configured):
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

    This function uses a running total and residual to ensure we're accurate
    in computing totals to equal bots_requested.

    Args:
      bots_requested(int): Total number of bots requested.
      region_restrictions(list[RegionRestriction]): Regional preferences
        from config.

    Returns:
      list[RegionalAction], region wise distribution of bots requested.
    """
    D = decimal.Decimal

    preceding_weight_sum = D('0')
    bots_requested = D(bots_requested)
    total_weight = sum(
        [D(restriction.weight) for restriction in region_restrictions])

    actions = []
    for restriction in region_restrictions:
      current_weight = D(restriction.weight)
      tot_alloc = (bots_requested *
                   (preceding_weight_sum + current_weight)) / total_weight
      cur_alloc = bots_requested * preceding_weight_sum / total_weight
      preceding_weight_sum = preceding_weight_sum + current_weight
      new_alloc = tot_alloc.quantize(0) - cur_alloc.quantize(0)
      actions.append(
          ScalingAction.RegionalAction(region=restriction.region,
                                       prefix=restriction.prefix,
                                       bots_requested=int(new_alloc)))

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

  def _make_swarming_calls(self, policy):
    """Makes the individual Swarming calls via CLI

    Args:
      policy(BotPolicy): individual bot policy config

    Returns:
      results(dict): Dict containing bot and task stats
    """
    dimensions = self.unpack_policy_dimensions(policy.swarming_dimensions)
    bot_stats_hold = None
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
    return {'bot_stats': bot_stats_hold, 'task_stats': task_stats_hold}

  def get_swarming_stats(self, bot_policy_config):
    """Determines the current Swarming stats per bot group.

    Args:
      bot_policy_config(BotPolicyCfg): Config define Policy for
        the RoboCrop.

    Returns:
      SwarmingStats:  bot and task stats named tuple.
    """
    futures = {}
    for policy in bot_policy_config.bot_policies:
      fut = self.m.futures.spawn(self._make_swarming_calls, policy=policy)
      futures[fut] = policy
    bot_stats = []
    task_stats = []
    for fut in self.m.futures.iwait(futures.keys()):
      stats = fut.result()
      bot_stats.append(stats['bot_stats'])
      task_stats.extend(stats['task_stats'])
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

  def reduce_bot_policy_config_for_table(self, bot_policy_config):
    """ Reduces bot_policy_config fields prior to sending to bb tables.

    Args:
      bot_policy_config(BotPolicyCfg): Config define Policy for
        the RoboCrop.

    Returns:
      str, scaled down config that only includes data needed
      for plx
    """
    config = jsonpb.MessageToDict(bot_policy_config)

    # Create necessary fields to populate
    reduced_config = []

    # Loop though bot policies and grab important fields for bb tables
    for policy in config['botPolicies']:
      bot_policy = {}
      bot_policy['bot_group'] = str(policy['botGroup'])
      bot_policy['policy_mode'] = policy['policyMode']
      reduced_config.append(bot_policy)
    return ReducedBotPolicyCfg(bot_policies=reduced_config)

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
    futures = {}
    for scaling_action in robocrop_actions.scaling_actions:
      if scaling_action.actionable == ScalingAction.YES:
        for action in scaling_action.regional_actions:
          config = gce_map.get(action.prefix, None)
          if config is not None:
            config.current_amount = action.bots_requested
            fut = self.m.futures.spawn(self.m.gce_provider.update_gce_config,
                                       bid=action.prefix, config=config)
            futures[fut] = scaling_action
    for fut in self.m.futures.iwait(futures.keys()):
      gce_configs.append(fut.result())
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
          base_count = config.current_amount
          if action.actionable == ScalingAction.YES:
            base_count = regional_action.bots_requested

          # Set resource utilization per region
          usage.vms += base_count
          usage.memory_gb += round(base_count * action.bot_type.memory_gb)
          usage.cpus += base_count * action.bot_type.cores_per_bot
          for disk in config.attributes.disk:
            usage.disk_gb += base_count * disk.size
            global_usage.disk_gb += base_count * disk.size
          usage.max_cpus += config.amount.max * action.bot_type.cores_per_bot
          # Roll up each regional collection to global
          global_usage.vms += base_count
          global_usage.cpus += (base_count * action.bot_type.cores_per_bot)
          global_usage.memory_gb += round(base_count *
                                          action.bot_type.memory_gb)
          global_usage.max_cpus += (
              config.amount.max * action.bot_type.cores_per_bot)
          resource_utilization[regional_action.region] = usage
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

  def _bot_swarming_stats(self, bot_group, cli_stats, b_min, b_max):
    """Helper method that formats the bot stats into a named tuple.

    Args:
      bot_group (str): name of bot group associated with stats.
      cli_stats (dict): swarming CLI dict of bot stats.
      b_min (int): bot floor from config
      b_max (int): bot ceiling from config

    Returns:
      BotStats: Swarming bot stats named tuple.
    """
    return BotStats(bot_group, int(cli_stats.get('busy', 0)),
                    int(cli_stats.get('count', 0)),
                    int(cli_stats.get('dead', 0)),
                    int(cli_stats.get('maintenance', 0)),
                    int(cli_stats.get('quarantined', 0)), b_min, b_max)

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
    if requested >= current_amount:
      if bot_policy.scaling_mode == BotPolicy.STEPPED:
        bots_requested = current_amount + min(
            (requested - current_amount),
            bot_policy.scaling_restriction.step_size)
      else:
        bots_requested = requested
    else:
      if (bot_policy.scaling_mode == BotPolicy.STEPPED or
          bot_policy.scaling_mode == BotPolicy.STEPPED_DECREASE):
        bots_requested = current_amount - min(
            (current_amount - requested),
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
    if self._hours_between_builds is None:
      self._hours_between_builds = self._estimate_hours_between_builds()
    return (bot_policy.scaling_restriction.bot_ceiling - bot_base) * (
        bot_policy.bot_type.hourly_cost * self._hours_between_builds)

  def _estimate_hours_between_builds(self):
    """Determine how often this builder runs, based on the past day's builds.

    Returns:
      float, the mean interval between recent runs of this builder in hours.
    """
    with self.m.step.nest('estimate time between builds') as presentation:

      def _warn_about_default(message_prefix):
        """Present a warning that we're using default values."""
        presentation.step_text = '{}: assuming default {} hrs/build'.format(
            message_prefix, DEFAULT_HOURS_BETWEEN_BUILDS)
        presentation.status = self.m.step.WARNING

      predicate = builds_service_pb2.BuildPredicate(
          builder=self.m.buildbucket.build.builder,
          create_time=common_pb2.TimeRange(
              # Look back 1hr+1min to catch the 1hr-old build
              start_time=timestamp_pb2.Timestamp(
                  seconds=self.m.buildbucket.build.create_time.ToSeconds() -
                  61 * 60,
              ),
              end_time=timestamp_pb2.Timestamp(
                  seconds=self.m.buildbucket.build.create_time.ToSeconds() -
                  1 * 60,
              ),
          ),
      )
      try:
        recent_builds = self.m.buildbucket.search(
            predicate, step_name="search for builds in past hour")
      except self.m.step.StepFailure:  # pragma: no cover
        _warn_about_default('Buildbucket search failed')
        return DEFAULT_HOURS_BETWEEN_BUILDS

      if not recent_builds:  # pragma: no cover
        _warn_about_default('Buildbucket search returned no builds')
        return DEFAULT_HOURS_BETWEEN_BUILDS
      return 1.0 / len(recent_builds)
