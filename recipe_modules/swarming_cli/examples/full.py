# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the swarming_cli module."""

from PB.chromiumos.bot_scaling import SwarmingDimension

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'bot_scaling',
    'swarming_cli',
]



def RunSteps(api):
  dimensions = [
      SwarmingDimension(name='role', value='cq', values=['cq']),
      SwarmingDimension(name='bot_size', value='large', values=['large'])
  ]
  query_dim = api.bot_scaling.unpack_policy_dimensions(dimensions)
  swarming_instance = 'chromeos-swarming.appspot.com'
  for dim in query_dim:
    bot_count = api.swarming_cli.get_bot_counts(
        swarming_instance, dim, bot_group=api.properties.get('bot_group'))
  api.assertions.assertEqual(int(bot_count.get('busy'), 0), 21)
  api.assertions.assertEqual(int(bot_count.get('count'), 0), 23)

  dimensions = [
      SwarmingDimension(name='role', value='foo', values=['foo']),
      SwarmingDimension(name='bot_size', value='large', values=['large'])
  ]
  query_dim = api.bot_scaling.unpack_policy_dimensions(dimensions)
  for dim in query_dim:
    bot_count = api.swarming_cli.get_bot_counts(
        swarming_instance, dim, bot_group=api.properties.get('bot_group'))
  api.assertions.assertEqual(int(bot_count.get('busy', 0)), 0)

  dimensions = [
      SwarmingDimension(name='role', value='cq', values=['cq']),
      SwarmingDimension(name='bot_size', value='large', values=['large'])
  ]
  query_dim = api.bot_scaling.unpack_policy_dimensions(dimensions)
  TASK_STATES = ['RUNNING', 'PENDING']
  for dim in query_dim:
    for state in TASK_STATES:
      task_count = api.swarming_cli.get_task_counts(
          dim, state, -48, swarming_instance,
          bot_group=api.properties.get('bot_group'))
  api.assertions.assertEqual(int(task_count.get('busy', 0)), 0)

  pend_time = api.swarming_cli.get_max_pending_time(query_dim[0], -48,
                                                    swarming_instance)
  api.assertions.assertLess(pend_time, 2.1)
  api.assertions.assertGreater(pend_time, 1.9)


def GenTests(api):
  yield api.test('basic')

  yield api.test('specifying-bot-group',
                 api.properties(bot_group='some-bot-group'))
