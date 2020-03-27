# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'swarming_cli',
]


def RunSteps(api):
  bot_count = api.swarming_cli.get_bot_counts(dimensions={
      'role': 'cq',
      'bot_size': 'large'
  })
  api.assertions.assertEqual(int(bot_count.get('busy'), 0), 21)
  api.assertions.assertEqual(int(bot_count.get('count'), 0), 23)

  bot_count = api.swarming_cli.get_bot_counts(dimensions={
      'role': 'foo',
      'bot_size': 'large'
  })
  api.assertions.assertEqual(int(bot_count.get('busy', 0)), 0)

  task_count = api.swarming_cli.get_task_counts(dimensions={
      'role': 'cq',
      'bot_size': 'large'
  })
  api.assertions.assertEqual(int(task_count.get('count', 0)), 23)


def GenTests(api):
  yield api.test('basic')
