# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'checkpoint',
]



def RunSteps(api: RecipeApi):
  with api.assertions.assertRaises(ValueError):
    api.checkpoint.update_summary('foo', 'BAD_STATUS')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(**{'$chromeos/checkpoint': {
          'retry': True,
      }}),
      api.post_process(post_process.DropExpectation),
  )
