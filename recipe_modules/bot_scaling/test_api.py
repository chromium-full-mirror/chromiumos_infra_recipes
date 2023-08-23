# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from recipe_engine import recipe_test_api
from PB.chromiumos.bot_scaling import BotPolicy, BotPolicyCfg, BotType
from PB.go.chromium.org.luci.gce.api.config.v1.config import Amount, Config, Configs, Disk, VM


class BotScalingTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the bot_scaling module."""

  @staticmethod
  def gce_provider_config() -> Configs:
    """Return a sample list of GCE provider configs."""
    return Configs(vms=[
        Config(prefix='prefix-first', amount=Amount(min=5, max=30),
               current_amount=19, attributes=_get_disk()),
        Config(prefix='prefix-second', amount=Amount(min=5, max=45),
               current_amount=23, attributes=_get_disk()),
        Config(prefix='prefix-third', amount=Amount(min=5, max=30),
               current_amount=18, attributes=_get_disk()),
        Config(prefix='prefix-fourth', amount=Amount(min=5, max=45),
               current_amount=25, attributes=_get_disk()),
    ])

  @staticmethod
  def gce_provider_config_ceiling() -> Configs:
    """Return a sample list of GCE provider configs with near-maxed amounts."""
    return Configs(vms=[
        Config(prefix='prefix-first', amount=Amount(min=5, max=30),
               current_amount=29, attributes=_get_disk()),
        Config(prefix='prefix-second', amount=Amount(min=5, max=45),
               current_amount=44, attributes=_get_disk()),
        Config(prefix='prefix-third', amount=Amount(min=5, max=30),
               current_amount=25, attributes=_get_disk()),
        Config(prefix='prefix-fourth', amount=Amount(min=5, max=45),
               current_amount=42, attributes=_get_disk()),
    ])

  @staticmethod
  def get_bot_type() -> BotType:
    """Return a sample BotType for tests."""
    return BotType(
        bot_size='small',
        cores_per_bot=4,
        hourly_cost=.337,
        memory_gb=16,
    )

  def robocrop_bot_policy_config(self,
                                 policy_mode: BotPolicy = BotPolicy.CONFIGURED,
                                 repeated: int = 1) -> BotPolicyCfg:
    """Return a sample BotPolicyCfg for tests.

    Args:
      policy_mode: The policy mode to set for all BotPolicies.
      repeated: The number of BotPolicies to include in the config.
    """
    scaling_restriction = BotPolicy.ScalingRestriction(
        min_idle=25,
        step_size=25,
        bot_fallback=45,
    )
    bot_type = self.get_bot_type()

    region_restrictions = [
        BotPolicy.RegionRestriction(
            region='first',
            prefix='prefix-first',
            weight=0.25,
        ),
        BotPolicy.RegionRestriction(
            region='second',
            prefix='prefix-second',
            weight=0.25,
        ),
        BotPolicy.RegionRestriction(
            region='third',
            prefix='prefix-third',
            weight=0.2,
        ),
        BotPolicy.RegionRestriction(
            region='fourth',
            prefix='prefix-fourth',
            weight=0.3,
        ),
    ]
    bot_policy_cfg = []
    for x in range(repeated):
      bot_policy_cfg.append(
          BotPolicy(bot_group=f'cq{x}', bot_type=bot_type,
                    scaling_restriction=scaling_restriction,
                    region_restrictions=region_restrictions,
                    policy_mode=policy_mode, scaling_mode=BotPolicy.STEPPED,
                    swarming_instance='chromeos-swarming.appspot.com',
                    application='chromeos'))
    return BotPolicyCfg(bot_policies=bot_policy_cfg)


def _get_disk() -> VM:
  """Return a sample VM with a sample disk."""
  return VM(disk=[Disk(size=750)])
