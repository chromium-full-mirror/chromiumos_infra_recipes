# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
    'cros_infra_config',
    'recipe_engine/time',
]

from PB.chromiumos.bot_scaling import BotPolicy, BotPolicyCfg
from recipe_engine import post_process

MONDAY_3_25_PM = 1607383500
TUESDAY_6_00_AM = 1607436000
FRIDAY_3_25_PM = 1607729100
FRIDAY_6_55_PM = 1607741700
FRIDAY_8_00_PM = 1607745600

IN_DAYTIME_WINDOW_RESULTS = {
    'ceiling': 75,
    'floor': 10,
    'floor_monitored': 25,
}

OUT_OF_DAYTIME_WINDOW_RESULTS = {
    'ceiling': -1,
    'floor': -1,
    'floor_monitored': 25,
}

EXPECTED_RESULTS = {
    MONDAY_3_25_PM: IN_DAYTIME_WINDOW_RESULTS,
    TUESDAY_6_00_AM: OUT_OF_DAYTIME_WINDOW_RESULTS,
    FRIDAY_3_25_PM: IN_DAYTIME_WINDOW_RESULTS,
    FRIDAY_6_55_PM: OUT_OF_DAYTIME_WINDOW_RESULTS,
    FRIDAY_8_00_PM: OUT_OF_DAYTIME_WINDOW_RESULTS,
}


def RunSteps(api):
  bot_policy_config = api.bot_scaling.test_api.robocrop_bot_policy_config_mixed(
  )
  gce_config = api.bot_scaling.test_api.gce_provider_config_scheduled_resize()
  updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, gce_config, application='Chrome')

  seeded_time = api.time.time()
  for policy in updated_bot_policy.bot_policies:
    if policy.bot_group == 'resize_scheduled':
      api.assertions.assertEqual(policy.scaling_restriction.bot_ceiling,
                                 EXPECTED_RESULTS[seeded_time]['ceiling'])
      api.assertions.assertEqual(policy.scaling_restriction.bot_floor,
                                 EXPECTED_RESULTS[seeded_time]['floor'])
    else:
      api.assertions.assertEqual(policy.scaling_restriction.bot_ceiling, 110)
      api.assertions.assertEqual(policy.scaling_restriction.bot_floor, 15)

  bot_policy_config = api.bot_scaling.test_api.robocrop_bot_policy_config_mixed(
      policy_mode=BotPolicy.MONITORED)
  floor_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, gce_config, application='Chrome')
  for policy in floor_bot_policy.bot_policies:
    if policy.bot_group == 'resize_scheduled':
      api.assertions.assertEqual(policy.scaling_restriction.bot_ceiling,
                                 EXPECTED_RESULTS[seeded_time]['ceiling'])
      api.assertions.assertEqual(
          policy.scaling_restriction.bot_floor,
          EXPECTED_RESULTS[seeded_time]['floor_monitored'])
    else:
      api.assertions.assertEqual(policy.scaling_restriction.bot_ceiling, 110)
      api.assertions.assertEqual(policy.scaling_restriction.bot_floor, 25)


def GenTests(api):
  yield api.test(
      'basic_monday',
      api.time.seed(MONDAY_3_25_PM),
      api.time.step(0),
  )
  yield api.test(
      'basic_friday',
      api.time.seed(FRIDAY_3_25_PM),
      api.time.step(0),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'almost_evening',
      api.time.seed(FRIDAY_6_55_PM),
      api.time.step(0),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'evening',
      api.time.seed(FRIDAY_8_00_PM),
      api.time.step(0),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'morning',
      api.time.seed(TUESDAY_6_00_AM),
      api.time.step(0),
      api.post_process(post_process.DropExpectation),
  )
