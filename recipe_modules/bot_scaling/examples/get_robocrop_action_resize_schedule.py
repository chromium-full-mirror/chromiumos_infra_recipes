# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'bot_scaling',
    'cros_infra_config',
    'recipe_engine/time',
]

from PB.chromiumos.bot_scaling import ScalingAction
from recipe_engine import post_process

MONDAY_3_25_PM = 1607383500
TUESDAY_6_00_AM = 1607436000
FRIDAY_3_25_PM = 1607729100
FRIDAY_6_55_PM = 1607741700
FRIDAY_8_00_PM = 1607745600

# If time is not within weekday daytime window, there should not be a scaling
# action for policies with resize schedules.
EXPECTED_SCALING_ACTION_BOT_GROUPS = {
    MONDAY_3_25_PM: {
        'resize_scheduled': ScalingAction.YES,
        'no_resize': ScalingAction.YES
    },
    TUESDAY_6_00_AM: {
        'resize_scheduled': ScalingAction.NO,
        'no_resize': ScalingAction.YES
    },
    FRIDAY_3_25_PM: {
        'resize_scheduled': ScalingAction.YES,
        'no_resize': ScalingAction.YES
    },
    FRIDAY_6_55_PM: {
        'resize_scheduled': ScalingAction.NO,
        'no_resize': ScalingAction.YES
    },
    FRIDAY_8_00_PM: {
        'resize_scheduled': ScalingAction.NO,
        'no_resize': ScalingAction.YES
    },
}


def RunSteps(api):
  bot_policy_config = api.bot_scaling.test_api.robocrop_bot_policy_config_mixed(
  )
  gce_config = api.bot_scaling.test_api.gce_provider_config_scheduled_resize()
  updated_bot_policy = api.bot_scaling.update_bot_policy_limits(
      bot_policy_config, gce_config, application='Chrome')
  swarming_stats = api.bot_scaling.get_swarming_stats(updated_bot_policy)

  robocrop_swarming_action = api.bot_scaling.get_robocrop_action(
      updated_bot_policy, gce_config, swarming_stats=swarming_stats)

  seeded_time = api.time.time()
  for scaling_action in robocrop_swarming_action.scaling_actions:
    expected_actionables = EXPECTED_SCALING_ACTION_BOT_GROUPS[seeded_time]
    api.assertions.assertEqual(
        scaling_action.actionable,
        expected_actionables[scaling_action.bot_group],
    )
    if scaling_action.actionable == ScalingAction.NO:
      api.assertions.assertEqual(scaling_action.estimated_savings, 0.0)


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
