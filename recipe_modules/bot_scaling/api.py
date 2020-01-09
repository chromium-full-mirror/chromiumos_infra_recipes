# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.bot_scaling import ScalingAction
from recipe_engine import recipe_api


class BotScalingApi(recipe_api.RecipeApi):
  """A module that determines how to scale bot groups."""

  def get_scaling_action(self, demand, bot_policy):
    """The overarching function that creates a ScalingAction for a bot group.

    Args:
      demand(int): Current demand for bots.
      bot_policy(BotPolicy): Config define Policy for a bot group.

    Returns:
      ScalingAction, comprehensive action to be taken by RoboCrop.
    """
    scaling_action = ScalingAction(bot_group=bot_policy.bot_group,
                                   bot_type=bot_policy.bot_type)

    scaling_action.bots_requested = self.get_bot_request(
        demand, bot_policy.scaling_restriction)

    scaling_action.regional_actions.extend(
        self.get_regional_actions(scaling_action.bots_requested,
                                  bot_policy.region_restrictions))
    # TODO: Use step_size and history to determine if this action
    # is actionable.
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
                restriction.weight * bots_requested / total_weight),
        ) for restriction in region_restrictions
    ]
    return actions
