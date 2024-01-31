# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'bot_cost',
    'cros_tags',
]



def RunSteps(api: RecipeApi):
  api.bot_cost.set_build_cost()
  api.assertions.assertEqual(api.bot_cost._bot_size, 'unknown')


def GenTests(api: RecipeTestApi):

  bld_msg = build_pb2.Build(id=123, status='SUCCESS')
  bld_msg.infra.swarming.bot_dimensions.extend(
      api.cros_tags.tags(bot_size='n2d-standard-1234567'))

  yield api.test(
      'no-fail-unknown-bot-size',
      api.buildbucket.build(bld_msg),
      api.post_process(post_process.PropertyEquals, 'build_cost', 0.0),
  )
