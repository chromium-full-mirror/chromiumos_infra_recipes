# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
]

from PB.chromiumos.bot_scaling import BotPolicy, BotType


def RunSteps(api):
  scaling_restriction = BotPolicy.ScalingRestriction(
      bot_ceiling=100,
      bot_floor=20,
      min_idle=0,
      step_size=10,
      bot_fallback=45,
  )
  bot_type = BotType(
      bot_size="small",
      cores_per_bot=4,
  )
  region_restrictions = [
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
  ]
  bot_policy = BotPolicy(
      bot_group='cq',
      bot_type=bot_type,
      scaling_restriction=scaling_restriction,
      region_restrictions=region_restrictions,
  )

  scaling_action = api.bot_scaling.get_scaling_action(90, bot_policy)

  api.assertions.assertEqual(scaling_action.bots_requested, 90)
  api.assertions.assertEqual(scaling_action.bot_type, bot_type)
  api.assertions.assertEqual(scaling_action.bot_group, 'cq')
  api.assertions.assertEqual(len(scaling_action.regional_actions), 2)
  api.assertions.assertEqual(scaling_action.regional_actions[0].region, 'first')
  api.assertions.assertEqual(scaling_action.regional_actions[0].prefix,
                             'prefix-first')
  api.assertions.assertEqual(scaling_action.regional_actions[0].bots_requested,
                             45)
  api.assertions.assertEqual(scaling_action.regional_actions[1].region,
                             'second')
  api.assertions.assertEqual(scaling_action.regional_actions[1].prefix,
                             'prefix-second')
  api.assertions.assertEqual(scaling_action.regional_actions[1].bots_requested,
                             45)


def GenTests(api):
  yield api.test('basic')
