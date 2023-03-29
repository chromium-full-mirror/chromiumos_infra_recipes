# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'bot_cost',
    'cros_tags',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  api.assertions.assertEqual(api.bot_cost._bot_size, None)
  api.assertions.assertRaises(ValueError, api.bot_cost.set_build_cost)


def GenTests(api: RecipeTestApi):

  def test(name: str, status: str, bot_size: str, test_status='SUCCESS'):
    bld_msg = build_pb2.Build(id=123, status=status)
    bld_msg.infra.swarming.bot_dimensions.extend(
        api.cros_tags.tags(bot_size=bot_size))
    return api.test(name, api.buildbucket.build(bld_msg), status=test_status)

  # TODO (b/275363240): audit this test.
  yield test(
      'bad-size',
      status='STARTED',
      bot_size='bad',
      test_status='FAILURE',
  )
