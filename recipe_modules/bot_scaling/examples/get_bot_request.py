# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.bot_scaling import BotPolicy

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
]



def RunSteps(api):

  # Without min_idle, bot group reflects demand.
  scaling_restriction = BotPolicy.ScalingRestriction(
      bot_ceiling=100,
      bot_floor=20,
      min_idle=0,
      step_size=10,
      bot_fallback=45,
  )
  bots_to_request = api.bot_scaling.get_bot_request(90, scaling_restriction)
  api.assertions.assertEqual(bots_to_request, 90)

  # When demand + min_idle > ceiling.
  scaling_restriction = BotPolicy.ScalingRestriction(
      bot_ceiling=100,
      bot_floor=20,
      min_idle=10,
      step_size=10,
      bot_fallback=45,
  )
  bots_to_request = api.bot_scaling.get_bot_request(120, scaling_restriction)
  api.assertions.assertEqual(bots_to_request, 100)

  # When demand + min_idle < floor.
  scaling_restriction = BotPolicy.ScalingRestriction(
      bot_ceiling=100,
      bot_floor=20,
      min_idle=-20,
      step_size=10,
      bot_fallback=45,
  )
  bots_to_request = api.bot_scaling.get_bot_request(10, scaling_restriction)
  api.assertions.assertEqual(bots_to_request, 20)


def GenTests(api):
  yield api.test('basic')
