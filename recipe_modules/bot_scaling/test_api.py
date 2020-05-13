# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.chromiumos.bot_scaling import BotPolicy, BotType, ScalingAction
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.gce.api.config.v1.config import Amount, Config, Configs


class BotScalingTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_history module."""

  def gce_provider_config(self):
    return Configs(vms=[
        Config(prefix='prefix-first', amount=Amount(min=5, max=30),
               current_amount=19),
        Config(prefix='prefix-second', amount=Amount(min=5, max=45),
               current_amount=23),
        Config(prefix='prefix-third', amount=Amount(min=5, max=30),
               current_amount=18),
        Config(prefix='prefix-fourth', amount=Amount(min=5, max=45),
               current_amount=25),
    ])

  def gce_provider_config_ceiling(self):
    return Configs(vms=[
        Config(prefix='prefix-first', amount=Amount(min=5, max=30),
               current_amount=29),
        Config(prefix='prefix-second', amount=Amount(min=5, max=45),
               current_amount=44),
        Config(prefix='prefix-third', amount=Amount(min=5, max=30),
               current_amount=25),
        Config(prefix='prefix-fourth', amount=Amount(min=5, max=45),
               current_amount=42),
    ])

  def get_bot_type(self):
    return BotType(
        bot_size="small",
        cores_per_bot=4,
        hourly_cost=.337,
    )

  def robocrop_bot_policy_config(self):
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
    return BotPolicy(
        bot_group='cq',
        bot_type=bot_type,
        scaling_restriction=scaling_restriction,
        region_restrictions=region_restrictions,
        policy_mode=BotPolicy.CONFIGURED,
        scaling_mode=BotPolicy.STEPPED,
    )
