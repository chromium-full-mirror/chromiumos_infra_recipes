# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'bot_scaling',
    'cros_infra_config',
]


def RunSteps(api):
  bot_policy_config = api.cros_infra_config.get_bot_policy_config()

  swarming_stats = api.bot_scaling.get_swarming_stats(bot_policy_config)
  task_stats = swarming_stats.get('task_stats', {})
  bot_stats = swarming_stats.get('bot_stats', {})
  api.assertions.assertEqual(len(task_stats), 1)
  api.assertions.assertEqual(
      int(task_stats.get('cq').get('RUNNING').get('count', 0)), 23)
  api.assertions.assertEqual(
      int(task_stats.get('cq').get('PENDING').get('count', 0)), 23)
  api.assertions.assertEqual(int(bot_stats.get('cq').get('count', 0)), 23)
  api.assertions.assertEqual(int(bot_stats.get('cq').get('busy', 0)), 21)


def GenTests(api):
  yield api.test('basic')
