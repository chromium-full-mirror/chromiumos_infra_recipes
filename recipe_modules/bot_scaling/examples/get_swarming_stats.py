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
  api.assertions.assertEqual(len(swarming_stats), 1)


def GenTests(api):
  yield api.test('basic')
