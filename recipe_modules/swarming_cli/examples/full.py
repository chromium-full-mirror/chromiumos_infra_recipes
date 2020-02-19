# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'swarming_cli',
]


def RunSteps(api):
  bot_count = api.swarming_cli.get_bot_count(
      dimensions={
          'role': 'cq',
          'bot_size': 'large'
      }, state='IDLE')
  api.assertions.assertEqual(bot_count, 2)

  with api.assertions.assertRaises(ValueError):
    api.swarming_cli.get_bot_count(dimensions={'role': 'test'}, state='FOO')


def GenTests(api):
  yield api.test('basic')
