# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'bot_scaling',
    'recipe_engine/assertions',
    'swarming_cli',
]

from PB.chromiumos.bot_scaling import SwarmingDimension


def RunSteps(api):
  dimensions = [
      SwarmingDimension(name="role", value="cq", values=["cq"]),
      SwarmingDimension(name="bot_size", value="large", values=["large"])
  ]
  query_dim = api.bot_scaling.unpack_policy_dimensions(dimensions)
  for dim in query_dim:
    bot_count = api.swarming_cli.get_bot_counts(dim)
  api.assertions.assertEqual(int(bot_count.get('busy'), 0), 21)
  api.assertions.assertEqual(int(bot_count.get('count'), 0), 23)

  dimensions = [
      SwarmingDimension(name="role", value="foo", values=["foo"]),
      SwarmingDimension(name="bot_size", value="large", values=["large"])
  ]
  query_dim = api.bot_scaling.unpack_policy_dimensions(dimensions)
  for dim in query_dim:
    bot_count = api.swarming_cli.get_bot_counts(dim)
  api.assertions.assertEqual(int(bot_count.get('busy', 0)), 0)

  dimensions = [
      SwarmingDimension(name="role", value="cq", values=["cq"]),
      SwarmingDimension(name="bot_size", value="large", values=["large"])
  ]
  query_dim = api.bot_scaling.unpack_policy_dimensions(dimensions)
  TASK_STATES = ['RUNNING', 'PENDING']
  for dim in query_dim:
    for state in TASK_STATES:
      task_count = api.swarming_cli.get_task_counts(dim, state)
  api.assertions.assertEqual(int(task_count.get('busy', 0)), 0)


def GenTests(api):
  yield api.test('basic')
