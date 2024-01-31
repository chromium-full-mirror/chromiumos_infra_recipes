# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.bot_cost.examples.test import TestProperties
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_cost',
    'cros_tags',
]


PROPERTIES = TestProperties


def RunSteps(api: RecipeApi, properties: TestProperties):
  with api.bot_cost.build_cost_context():
    with api.step.nest(properties.name):
      build_cost = api.bot_cost._calculate_build_cost()
      if properties.expect_cost:
        api.assertions.assertNotEqual(0, build_cost)
      else:
        api.assertions.assertEqual(0, build_cost)


def GenTests(api: RecipeTestApi):

  def test(name: str, status: str, start_time: int = None, end_time: int = None,
           update_time: int = None, bot_size: str = 'small',
           expect_cost: bool = True) -> TestData:
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
    build = api.buildbucket.build(bld_msg)
    if status != 'STATUS_UNSPECIFIED':
      build += api.buildbucket.simulated_get(
          bld_msg, step_name='%s.calculate build cost.buildbucket.get' % name)
    build += api.properties(
        TestProperties(name=name, bot_size=bot_size, expect_cost=expect_cost))
    return api.test(name, build, *[])

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
