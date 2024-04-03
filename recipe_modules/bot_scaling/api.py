# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module that determines how to scale bot groups based on demand."""

import dataclasses
import decimal
import itertools
import math
from typing import Dict, List

from PB.chromiumos.bot_scaling import ApplicationUtilization
from PB.chromiumos.bot_scaling import BotPolicy
from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.chromiumos.bot_scaling import ReducedBotPolicyCfg
from PB.chromiumos.bot_scaling import ResourceUtilization
from PB.chromiumos.bot_scaling import RoboCropAction
from PB.chromiumos.bot_scaling import ScalingAction
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.gce.api.config.v1.config import Config
from PB.go.chromium.org.luci.gce.api.config.v1.config import Configs

from google.protobuf import json_format as jsonpb
from google.protobuf import timestamp_pb2
from recipe_engine import recipe_api

DEFAULT_HOURS_BETWEEN_BUILDS = 0.167
TASK_STATES = ['RUNNING', 'PENDING']


@dataclasses.dataclass
class BotStats:
  """Statistics about how many bots are in each state."""
  bot_group: str
  busy: int
  count: int
  dead: int
  maintenance: int
  quarantined: int
  min: int
  max: int


@dataclasses.dataclass
class TaskStats:
  """Statistics about how many tasks are in each state."""
  bot_group: str
  task_state: str
  count: int


@dataclasses.dataclass
class SwarmingStats:
  """Helper class to contain bot and task statistics from Swarming."""
  bot_stats: List[BotStats]
  task_stats: List[TaskStats]


class BotScalingApi(recipe_api.RecipeApi):
  """A module that determines how to scale bot groups."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._hours_between_builds = None

  def get_num_cores(self):
    """Get the number of cores on the host."""
    return int(
        self.m.easy.stdout_step('count online CPUs', ['nproc'],
                                test_stdout=' 8\n').strip())

  def drop_cpu_cores(self, min_cpus_left=4, max_drop_ratio=0.75,
                     test_rand=None):
    """Gather data on build's per core scaling efficiencies.

    Gather data on per build CPU efficiency by dropping cores on the
    instances. Sets a property 'enabled_cpu_cores', with the final count.

    Warning!: We've embedded an assumption that we will reboot between tasks
    so these changes are effectual for a single run only.

    Note: This is only enabled on non-led staging builds.

    Args:
      min_cpus_left (int): Do not drop below this number of cores.
      max_drop_ratio (float): The maximum ratio of cpus to drop relative to
        the overall count.
      test_rand (flaot): Set the max_drop_ratio to this instead of the uniform
        random distribution (for testing).

    Returns: The number of cpus dropped.
    """
    drop_n_cores = 0
    # Do not drop cores for production builds or led runs.
    if (self.m.led.run_id or self.m.led.led_build or
        not self.m.cros_infra_config.is_staging):
      return drop_n_cores

    min_cpus_left = max(1, min_cpus_left)

    with self.m.step.nest('dropping cores') as pres:
      # Establish the CPU count.
      n_proc = self.get_num_cores()

      # Validation check that state is fresh.
      online_intervals = self.m.easy.stdout_step(
          'ensure all cpus online',
          ['sudo', 'cat', '/sys/devices/system/cpu/offline'])
      if online_intervals.strip():
        pres.step_text = 'CPUs are already offline! You must reboot to use this feature!'
        pres.status = self.m.step.WARNING
        self.m.easy.set_properties_step(enabled_cpu_cores=n_proc)
        return 0

      # Pick a random number of cores to drop to target.
      rand = test_rand if isinstance(
          test_rand, float) else self.m.random.uniform(0.0, max_drop_ratio)
      drop_n_cores = min(int(math.floor(rand * n_proc)), n_proc - min_cpus_left)

      # Drop the cores.
      for c in range(0, drop_n_cores):
        self.m.step('drop {} cpu cores'.format(drop_n_cores), [
            'sudo', 'tee', '/sys/devices/system/cpu/cpu{}/online'.format(c + 1)
        ], stdin=self.m.raw_io.input_text(str(0)))
      # Set output property with value of remaining cores.
    self.m.easy.set_properties_step(enabled_cpu_cores=n_proc - drop_n_cores)
    return drop_n_cores

  def get_robocrop_action(self, bot_policy_config, configs, swarming_stats):
    """Function to compute all the actions of this RoboCrop.

    Args:
      bot_policy_config(BotPolicyCfg): Config define Policy for the RoboCrop.
      configs(Configs): List of GCE Config objects.
      swarming_stats(SwarmingStats): Current Swarming bot and task counts, or
        None if there were errors fetching them.

    Returns:
      RoboCropAction, comprehensive action to be taken by RoboCrop.
    """
    scaling_actions = []
    missing_bot_fallbacks = []
    for policy in bot_policy_config.bot_policies:
      # swarming_stats will be None when if there were errors fetching them.
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
      ScalingAction, action to be taken on a single bot group by RoboCrop.
    """
    bots_requested = self.get_bot_request(demand,
                                          bot_policy.scaling_restriction)
    bots_configured = self.get_gce_bots_configured(
        bot_policy.region_restrictions, _get_prefix_to_gce_config(configs))
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

    scaling_action.bots_requested = _calculate_bot_adjustment(
        bot_policy, bots_requested, bots_configured)
    scaling_action.estimated_savings = self._calculate_estimated_savings(
        bot_policy, scaling_action.bots_requested, bots_configured, actionable)
    scaling_action.regional_actions.extend(
        self.get_regional_actions(scaling_action.bots_requested,
                                  bot_policy.region_restrictions))
    return scaling_action

  @staticmethod
  def get_bot_request(demand, scaling_restriction):
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

  @staticmethod
  def get_regional_actions(
      bots_requested: int,
      region_restrictions: List[BotPolicy.RegionRestriction]
  ) -> List[ScalingAction.RegionalAction]:
    """Determines regional distribution of bot requests.

    This function uses a running total and residual to ensure we're accurate
    in computing totals to equal bots_requested.

    Args:
      bots_requested: Total number of bots requested.
      region_restrictions: Regional preferences from config.

    Returns:
      Region wise distribution of bots requested.
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

  @staticmethod
  def get_swarming_demand(swarming_stats: SwarmingStats, bot_group: str) -> int:
    """Return the demand for bots in a bot group.

    Args:
      swarming_stats: Dataclass containing bot and task stats from Swarming.
      bot_group: Name of bot group.

    Returns:
      The current demand for bots in the group.
    """
    return sum(
        (stat.count
         for stat in swarming_stats.task_stats
         if stat.bot_group == bot_group and stat.task_state in TASK_STATES))

  def _make_swarming_calls(self, policy: BotPolicy) -> SwarmingStats:
    """Makes the individual Swarming calls via CLI.

    Args:
      policy: Individual bot policy config.

    Returns:
      Bot and task stats fetched from Swarming.
    """
    with self.m.step.nest(f'query swarming for {policy.bot_group}'):
      dimensions = self.unpack_policy_dimensions(policy.swarming_dimensions)
      bot_stats_hold = None
      task_stats_hold = []
      for dim in dimensions:
        # Bot counts get duplicated, due to the way dimensions are associated,
        # therefore we only need to count the first returned count.
        if not bot_stats_hold:
          bot_stats_hold = _bot_swarming_stats(
              policy.bot_group,
              self.m.swarming_cli.get_bot_counts(policy.swarming_instance, dim,
                                                 policy.bot_group),
              policy.scaling_restriction.bot_floor,
              policy.scaling_restriction.bot_ceiling)
        for state in TASK_STATES:
          task_stats_hold = _update_task_stats(
              policy.bot_group, state, task_stats_hold,
              self.m.swarming_cli.get_task_counts(dim, state,
                                                  policy.lookback_hours,
                                                  policy.swarming_instance,
                                                  policy.bot_group))
      return SwarmingStats(bot_stats=bot_stats_hold, task_stats=task_stats_hold)

  def get_swarming_stats(self, bot_policy_config):
    """Determines the current Swarming stats per bot group.

    Args:
      bot_policy_config(BotPolicyCfg): Config define Policy for
        the RoboCrop.

    Returns:
      SwarmingStats: Dataclass containing bot and task stats.
    """
    futures = {}
    for policy in bot_policy_config.bot_policies:
      fut = self.m.futures.spawn(self._make_swarming_calls, policy=policy)
      futures[fut] = policy
    bot_stats = []
    task_stats = []
    for fut in self.m.futures.iwait(futures.keys()):
      swarming_stats = fut.result()
      bot_stats.append(swarming_stats.bot_stats)
      task_stats.extend(swarming_stats.task_stats)
    bot_stats.sort(key=lambda x: x.bot_group)
    task_stats.sort(key=lambda x: x.bot_group)
    return SwarmingStats(bot_stats, task_stats)

  def get_current_gce_config(self, bot_policy_config):
    """Retrieves the current configuration from GCE Provider service.

    Args:
      bot_policy_config(BotPolicyCfg): Config define Policy for
        the RoboCrop.

    Returns:
      ConfigResponse (named_tuple), GCE Provider config definitions and missing
        configs.
    """
    prefixes = []
    for policy in bot_policy_config.bot_policies:
      for restriction in policy.region_restrictions:
        prefixes.append(restriction.prefix)
    return self.m.gce_provider.get_current_config(prefixes)

  @staticmethod
  def get_gce_bots_configured(region_restrictions: List[
      BotPolicy.RegionRestriction], config_map: Dict[str, Config]) -> int:
    """Sums the total number of configured bots per bot policy.

    Args:
      region_restrictions: Regional preferences from config.
      config_map: Map of prefix to GCE Config.

    Returns:
      Sum of the total number of bots in GCE Provider
    """
    policy_count = 0
    for restriction in region_restrictions:
      config = config_map.get(restriction.prefix, Config())
      policy_count += config.current_amount
    return policy_count

  @staticmethod
  def update_bot_policy_limits(bot_policy_config: BotPolicyCfg,
                               configs: Configs) -> BotPolicyCfg:
    """Sums the min and max bot numbers per bot policy.

    Args:
      bot_policy_config: Config define Policy for the RoboCrop.
      configs: GCE Configs.

    Returns:
      The original bot_policy_config, updated to reflect ScalingRestriction
      values.
    """
    config_map = _get_prefix_to_gce_config(configs)
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

  @staticmethod
  def reduce_bot_policy_config_for_table(
      bot_policy_config: BotPolicyCfg) -> str:
    """Reduces bot_policy_config fields prior to sending to bb tables.

    Args:
      bot_policy_config: Config define Policy for the RoboCrop.

    Returns:
      Scaled-down config that only includes data needed for Plx.
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
    gce_map = _get_prefix_to_gce_config(configs)
    futures = {}
    for scaling_action in robocrop_actions.scaling_actions:
      if scaling_action.actionable == ScalingAction.YES:
        for action in scaling_action.regional_actions:
          config = gce_map.get(action.prefix, None)
          if config is not None:
            config.current_amount = action.bots_requested
            config.attributes.label[
                'robocrop_bot_group'] = scaling_action.bot_group
            fut = self.m.futures.spawn(self.m.gce_provider.update_gce_config,
                                       bid=action.prefix, config=config)
            futures[fut] = scaling_action
    for fut in self.m.futures.iwait(futures.keys()):
      gce_configs.append(fut.result())
    return Configs(vms=gce_configs)

  @staticmethod
  def unpack_policy_dimensions(dimensions):
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

  @staticmethod
  def _get_quota_usage(scaling_actions, configs):
    """Method to calculate quota usage based on scaling actions.

    Args:
      robocrop_actions(list[ScalingAction]): Repeatable ScalingAction
        configs.
      configs(Configs): List of GCE Config objects.
    Returns:
      ResourceUtilization, total resource usage across all bot groups.
    """
    config_map = _get_prefix_to_gce_config(configs)
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
            predicate, step_name='search for builds in past hour')
      except self.m.step.StepFailure:  # pragma: no cover
        _warn_about_default('Buildbucket search failed')
        return DEFAULT_HOURS_BETWEEN_BUILDS

      if not recent_builds:  # pragma: no cover
        _warn_about_default('Buildbucket search returned no builds')
        return DEFAULT_HOURS_BETWEEN_BUILDS
      return 1.0 / len(recent_builds)


def _get_prefix_to_gce_config(configs: Configs) -> Dict[str, Config]:
  """Helper function that returns the prefix to Config map.

  Loads the proto and builds the map.

  Args:
    configs (Configs): list of GCE Provider Config meessages.

  Returns:
    Map of prefix to GCE Config.
  """
  return {c.prefix: c for c in configs.vms}


def _bot_swarming_stats(bot_group: str, cli_stats: Dict, b_min: int,
                        b_max: int) -> BotStats:
  """Helper function that formats the bot stats into a dataclass.

  Args:
    bot_group: name of bot group associated with stats.
    cli_stats: swarming CLI dict of bot stats.
    b_min: bot floor from config
    b_max: bot ceiling from config

  Returns:
    Dataclass containing the bot stats from cli_stats.
  """
  return BotStats(bot_group, int(cli_stats.get('busy', 0)),
                  int(cli_stats.get('count', 0)), int(cli_stats.get('dead', 0)),
                  int(cli_stats.get('maintenance', 0)),
                  int(cli_stats.get('quarantined', 0)), b_min, b_max)


def _update_task_stats(bot_group: str, state: str, task_stats: List[TaskStats],
                       cli_stats: Dict) -> List[TaskStats]:
  """Helper function that updates a list of TaskStats with data from cli_stats.

  If task_stats already includes an element matching bot_group and state, then
  that element's count will be updated from cli_stats. Otherwise, a new
  TaskStats will be appended with the count from cli_stats.

  Args:
    bot_group: name of bot group associated with stats.
    state: Swarming task state.
    task_stats: Swarming task stats already collected. Will be modified
      in-place.
    cli_stats: Dict of task stats from the Swarming CLI.

  Returns:
    An updated version of task_stats, now including data from cli_stats.
  """
  count = int(cli_stats.get('count', 0))
  for stat in task_stats:
    if stat.bot_group == bot_group and stat.task_state == state:
      stat.count += count
      break
  else:
    task_stats.append(TaskStats(bot_group, state, count))
  return task_stats


def _calculate_bot_adjustment(bot_policy: BotPolicy, requested: int,
                              current_amount: int) -> int:
  """Helper to calculate the number of bots to request.

  Args:
    bot_policy_config: Group Policy for RoboCrop.
    requested: number of bots needed.
    curent_amount: current number of bots configured.

  Returns:
    The number of bots to request.
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
    if bot_policy.scaling_mode in (BotPolicy.STEPPED,
                                   BotPolicy.STEPPED_DECREASE):
      bots_requested = current_amount - min(
          (current_amount - requested),
          bot_policy.scaling_restriction.step_size)
    else:
      bots_requested = requested
  return bots_requested
