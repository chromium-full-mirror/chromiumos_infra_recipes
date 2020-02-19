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
  status_map = {'cq': {'STARTED': 1000, 'SCHEDULED': 50}}

  robocrop_action = api.bot_scaling.get_robocrop_action(status_map,
                                                        bot_policy_config)
  api.assertions.assertEqual(len(robocrop_action.scaling_actions), 1)


def GenTests(api):
  yield api.test('basic')
