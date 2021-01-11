# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.chromiumos.bot_scaling import BotPolicy, BotPolicyCfg, BotType, ScalingAction
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.gce.api.config.v1.config import Amount, Config, Configs, Disk, VM, Schedule, TimePeriod, TimeOfDay


class BotScalingTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_history module."""

  def gce_provider_config(self):
    return Configs(vms=[
        Config(prefix='prefix-first', amount=Amount(min=5, max=30),
               current_amount=19, attributes=self._get_disk()),
        Config(prefix='prefix-second', amount=Amount(min=5, max=45),
               current_amount=23, attributes=self._get_disk()),
        Config(prefix='prefix-third', amount=Amount(min=5, max=30),
               current_amount=18, attributes=self._get_disk()),
        Config(prefix='prefix-fourth', amount=Amount(min=5, max=45),
               current_amount=25, attributes=self._get_disk()),
    ])

  def gce_provider_config_ceiling(self):
    return Configs(vms=[
        Config(prefix='prefix-first', amount=Amount(min=5, max=30),
               current_amount=29, attributes=self._get_disk()),
        Config(prefix='prefix-second', amount=Amount(min=5, max=45),
               current_amount=44, attributes=self._get_disk()),
        Config(prefix='prefix-third', amount=Amount(min=5, max=30),
               current_amount=25, attributes=self._get_disk()),
        Config(prefix='prefix-fourth', amount=Amount(min=5, max=45),
               current_amount=42, attributes=self._get_disk()),
    ])

  def gce_provider_config_scheduled_resize(self):
    changes = []
    # Weekend
    changes.append(
        Schedule(
            length=TimePeriod(seconds=158400),
            start=TimeOfDay(day=5, location='America/Los_Angeles',
                            time="19:00"),
            min=5,
            max=20,
        ))

    # Weekday daytimes
    for day in range(1, 6):
      changes.append(
          Schedule(
              length=TimePeriod(seconds=39600),
              start=TimeOfDay(day=day, location='America/Los_Angeles',
                              time="8:00"),
              min=5,
              max=30,
          ))

    return Configs(vms=[
        Config(prefix='prefix-first', amount=Amount(
            min=1, max=5, change=changes), current_amount=19,
               attributes=self._get_disk()),
        Config(prefix='prefix-second', amount=Amount(min=5, max=45),
               current_amount=23, attributes=self._get_disk()),
        Config(prefix='prefix-third', amount=Amount(min=5, max=50),
               current_amount=18, attributes=self._get_disk()),
        Config(prefix='prefix-fourth', amount=Amount(min=10, max=60),
               current_amount=25, attributes=self._get_disk()),
    ])

  def _get_disk(self):
    return VM(disk=[Disk(size=750)])

  def get_bot_type(self):
    return BotType(
        bot_size="small",
        cores_per_bot=4,
        hourly_cost=.337,
        memory_gb=16,
    )

  def robocrop_bot_policy_config(self, policy_mode=BotPolicy.CONFIGURED,
                                 repeated=1):
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
          BotPolicy(bot_group='cq{}'.format(x), bot_type=bot_type,
                    scaling_restriction=scaling_restriction,
                    region_restrictions=region_restrictions,
                    policy_mode=policy_mode, scaling_mode=BotPolicy.STEPPED,
                    swarming_instance='chromeos-swarming.appspot.com',
                    application='chromeos'))
    return BotPolicyCfg(bot_policies=bot_policy_cfg)

  def robocrop_bot_policy_config_mixed(self, policy_mode=BotPolicy.CONFIGURED):
    scaling_restriction = BotPolicy.ScalingRestriction(
        min_idle=25,
        step_size=25,
        bot_fallback=45,
    )
    bot_type = self.get_bot_type()

    region_restrictions = {
        'resize_scheduled': [
            BotPolicy.RegionRestriction(
                region='first',
                prefix='prefix-first',
                weight=0.5,
            ),
            BotPolicy.RegionRestriction(
                region='second',
                prefix='prefix-second',
                weight=0.5,
            ),
        ],
        'no_resize': [
            BotPolicy.RegionRestriction(
                region='third',
                prefix='prefix-third',
                weight=0.4,
            ),
            BotPolicy.RegionRestriction(
                region='fourth',
                prefix='prefix-fourth',
                weight=0.6,
            ),
        ],
    }
    bot_policy_cfg = []
    for bot_group, region_restriction in region_restrictions.iteritems():
      bot_policy_cfg.append(
          BotPolicy(bot_group=bot_group, bot_type=bot_type,
                    scaling_restriction=scaling_restriction,
                    region_restrictions=region_restriction,
                    policy_mode=policy_mode, scaling_mode=BotPolicy.STEPPED,
                    swarming_instance='chromeos-swarming.appspot.com',
                    application='chromeos'))
    return BotPolicyCfg(bot_policies=bot_policy_cfg)
