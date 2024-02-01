# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

"""Tests for bot_cost."""

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

from RECIPE_MODULES.chromeos.bot_cost.api import BOT_COST

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'bot_cost',
    'cros_tags',
]


def RunSteps(api: RecipeApi):
  with api.bot_cost.build_cost_context():
    pass


def GenTests(api: RecipeTestApi):

  def buildbucket_build(status: str, start_time: int = None,
                        end_time: int = None, update_time: int = None,
                        bot_size: str = 'e2-medium', bbid: int = None,
                        build_cost: float = 0.0) -> TestData:
    if start_time:
      start_time = timestamp_pb2.Timestamp(seconds=start_time)
    if end_time:
      end_time = timestamp_pb2.Timestamp(seconds=end_time)
    if update_time:
      update_time = timestamp_pb2.Timestamp(seconds=update_time)
    build = build_pb2.Build(id=bbid or 123, status=status,
                            start_time=start_time, end_time=end_time,
                            update_time=update_time)
    build.infra.swarming.bot_dimensions.extend(
        api.cros_tags.tags(bot_size=bot_size))
    if build_cost:
      build.output.properties['build_cost'] = build_cost
    return build

  build = buildbucket_build(status='SUCCESS', start_time=3600, end_time=7200,
                            bot_size='n2d-standard-8')
  yield api.test(
      'terminal-build',
      api.buildbucket.build(build),
      api.buildbucket.simulated_get(
          build,
          step_name='set build cost.calculate build cost.buildbucket.get'),
      api.post_check(post_process.PropertyEquals, 'build_cost',
                     round(BOT_COST['n2d-standard-8'] * 1, 4)),
      api.post_process(post_process.DropExpectation),
  )

  build = buildbucket_build(
      status='STARTED',
      start_time=3600,
      update_time=7200,
  )
  yield api.test(
      'started-build',
      api.buildbucket.build(build),
      api.buildbucket.simulated_get(
          build,
          step_name='set build cost.calculate build cost.buildbucket.get'),
      api.post_check(post_process.PropertyEquals, 'build_cost',
                     round(BOT_COST['e2-medium'] * 1, 4)),
      api.post_process(post_process.DropExpectation),
  )

  child_builds = [
      buildbucket_build(
          bbid=124,
          status='SUCCESS',
          start_time=3600,
          update_time=7200,
          build_cost=10.,
      ),
      buildbucket_build(
          bbid=125,
          status='SUCCESS',
          start_time=3600,
          update_time=7200,
      )
  ]
  yield api.test(
      'started-build-with-children',
      api.buildbucket.build(build),
      api.buildbucket.simulated_search_results(
          child_builds, step_name='set build cost.buildbucket.search'),
      api.buildbucket.simulated_get(
          build,
          step_name='set build cost.calculate build cost.buildbucket.get'),
      api.post_check(post_process.PropertyEquals, 'build_cost',
                     round(BOT_COST['e2-medium'] * 1 + 10., 4)),
      api.post_process(post_process.LogDoesNotContain, 'set build cost',
                       'child builds missing build_cost', ['124']),
      api.post_process(post_process.LogContains, 'set build cost',
                       'child builds missing build_cost', ['125']),
      api.post_process(post_process.DropExpectation),
  )

  build = buildbucket_build(
      status='SCHEDULED',
      start_time=3600,
      update_time=7200,
  )
  yield api.test(
      'scheduled-build',
      api.buildbucket.build(build),
      api.buildbucket.simulated_get(
          build,
          step_name='set build cost.calculate build cost.buildbucket.get'),
      api.post_check(post_process.PropertyEquals, 'build_cost', 0),
      api.post_process(post_process.DropExpectation),
  )

  build = buildbucket_build(status='STATUS_UNSPECIFIED')
  yield api.test(
      'unspecified',
      api.time.step(3600),
      api.post_check(post_process.PropertyEquals, 'build_cost',
                     round(BOT_COST['e2-medium'] * 1., 4)),
      api.buildbucket.build(build),
      api.post_process(post_process.DropExpectation),
  )
