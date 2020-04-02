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

  def previous_robocrop(self):
    """Generate a struct for the 'build_target_test_status' property.

    Returns:
      Build: Containing the expected output properties.
    """
    build = build_pb2.Build(id=123,
                            builder=build_pb2.BuilderID(builder='RoboCrop'),
                            status=common_pb2.SUCCESS)
    build.output.properties.update({
        'robocrop_action': self.robocrop_action_dict()
    })
    return build

  def robocrop_action_dict(self):
    return {
        "scalingActions": [{
            "botType": {
                "coresPerBot": 32,
                "botSize": "large"
            },
            "botsRequested":
                1500,
            "botGroup":
                "cq",
            "regionalActions": [{
                "prefix": "prefix-first",
                "region": "us-central1-b",
                "botsRequested": 367
            },
                                {
                                    "prefix": "prefix-second",
                                    "region": "us-central2-d",
                                    "botsRequested": 464
                                },
                                {
                                    "region": "prefix-third",
                                    "prefix": "chromeos-ci-cq-us-east1-d-x32",
                                    "botsRequested": 367
                                },
                                {
                                    "prefix": "prefix-fourth",
                                    "region": "us-west1-b",
                                    "botsRequested": 300
                                }]
        }]
    }

  def gce_provider_config(self):
    return Configs(vms=[
        Config(prefix='prefix-first', amount=Amount(min=5, max=20),
               current_amount=19),
        Config(prefix='prefix-second', amount=Amount(min=5, max=25),
               current_amount=23),
        Config(prefix='prefix-third', amount=Amount(min=5, max=20),
               current_amount=18),
        Config(prefix='prefix-fourth', amount=Amount(min=5, max=25),
               current_amount=25),
    ])

  def get_bot_type(self):
    return BotType(
        bot_size="small",
        cores_per_bot=4,
    )

  def robocrop_bot_policy_config(self):
    scaling_restriction = BotPolicy.ScalingRestriction(
        min_idle=1,
        step_size=5,
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
    )
