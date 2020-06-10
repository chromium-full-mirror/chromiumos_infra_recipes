# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_cost',
    'cros_tags',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.bot_cost.examples.test import TestProperties

from google.protobuf import timestamp_pb2

PROPERTIES = TestProperties


def RunSteps(api, properties):
  with api.bot_cost.build_cost_context():
    with api.step.nest(properties.name) as test_step:
      build_cost = api.bot_cost._calculate_build_cost()
      if properties.expect_cost:
        api.assertions.assertNotEqual(0, build_cost)
      else:
        api.assertions.assertEqual(0, build_cost)


def GenTests(api):

  def test(name, status, start_time=None, end_time=None, update_time=None,
           bot_size='small', expect_cost=True, extra=None):
    if start_time:
      start_time = timestamp_pb2.Timestamp(seconds=start_time)
    if end_time:
      end_time = timestamp_pb2.Timestamp(seconds=end_time)
    if update_time:
      update_time = timestamp_pb2.Timestamp(seconds=update_time)
    bld_msg = build_pb2.Build(id=123, status=status, start_time=start_time,
                              end_time=end_time, update_time=update_time)
    bld_msg.infra.swarming.bot_dimensions.extend(
        api.cros_tags.tags(bot_size=bot_size))
    return api.test(
        name, api.buildbucket.build(bld_msg),
        api.properties(
            TestProperties(name=name, bot_size=bot_size,
                           expect_cost=expect_cost)), *(extra or []))

  yield test('terminal-build', status='SUCCESS', start_time=5000,
             end_time=15000)

  yield test('started-build', status='STARTED', start_time=5000,
             update_time=15000)

  yield test('scheduled-build', status='SCHEDULED', start_time=5000,
             end_time=15000, update_time=15000, expect_cost=False)

  yield test('medium-bot', status='SUCCESS', start_time=5000, end_time=15000,
             bot_size='medium')

  # Covers led launched builds, too.
  yield test('unspecified', status='STATUS_UNSPECIFIED')
