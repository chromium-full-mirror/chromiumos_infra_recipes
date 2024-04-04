# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test case for api.bot_scaling.get_swarming_demand()."""

from typing import Generator

from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from RECIPE_MODULES.chromeos.bot_scaling import api as bot_scaling_api

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
]


def make_irrelevant_bot_stats(bot_group: str) -> bot_scaling_api.BotStats:
  """Return a BotStats object whose numbers don't matter.

  This will help us ensure that we only calculate demand for the bot group we
  care about, and ignore all others. The state numbers are so large that if we
  accidentally use them, it should be immediately obvious that something is
  wrong.
  """
  return bot_scaling_api.BotStats(bot_group, 1000, 2000, 200, 200, 200, 100,
                                  2000)


def make_irrelevant_task_stats(bot_group: str,
                               task_state: str) -> bot_scaling_api.TaskStats:
  """Return a TaskStats object whose numbers don't matter.

  This will help us ensure that we only calculate demand for the bot group we
  care about, and ignore all others. The count number is so large that if we
  accidentally use it, it should be immediately obvious that something is wrong.
  """
  return bot_scaling_api.TaskStats(bot_group, task_state, 10000)


def RunSteps(api: recipe_api.RecipeApi) -> None:
  our_bot_group = 'our-bot-group'
  swarming_stats = bot_scaling_api.SwarmingStats([], [])

  # Add a bunch of bot_stats and task_stats that don't match the bot_group.
  # These should be ignored.
  for i in range(3):
    bot_group = f'irrelevant-bot-group-{i}'
    swarming_stats.bot_stats.append(make_irrelevant_bot_stats(bot_group))
    swarming_stats.task_stats.append(
        make_irrelevant_task_stats(bot_group, 'RUNNING'))
    swarming_stats.task_stats.append(
        make_irrelevant_task_stats(bot_group, 'PENDING'))

  # Now the bot group we actually care about.
  # In this case, we have 18 total bots, of which 15 are busy.
  # The 2 dead bots, 3 maintenance bots, and 4 quarantined bots all contribute
  # to the count of 15 busy bots. The other 6 busy bots would be running tasks.
  # If we want enough bots to cover the 5 pending tasks, we need a total of 20
  # bots: 15 for the existing already-busy bots, plus 5 for the new tasks.
  # Equivalently, you could count that as 2 dead bots + 3 maintenance bots + 4
  # quarantined bots + 6 for the already-running tasks + 5 for the new tasks:
  # 2 + 3 + 4 + 6 + 5 = 20.
  swarming_stats.bot_stats.append(
      bot_scaling_api.BotStats(our_bot_group, 15, 18, 2, 3, 4, 1, 30))
  swarming_stats.task_stats.append(
      bot_scaling_api.TaskStats(our_bot_group, 'RUNNING', 6))
  swarming_stats.task_stats.append(
      bot_scaling_api.TaskStats(our_bot_group, 'PENDING', 5))

  # Add a few more irrelevant bot_stats and task_stats after the good ones.
  for i in range(4, 7):
    bot_group = f'irrelevant-bot-group-{i}'
    swarming_stats.bot_stats.append(make_irrelevant_bot_stats(bot_group))
    swarming_stats.task_stats.append(
        make_irrelevant_task_stats(bot_group, 'RUNNING'))
    swarming_stats.task_stats.append(
        make_irrelevant_task_stats(bot_group, 'PENDING'))

  demand = api.bot_scaling.get_swarming_demand(swarming_stats, our_bot_group)
  api.assertions.assertEqual(demand, 20)


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  yield api.test('basic')
