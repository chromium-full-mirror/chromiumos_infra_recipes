# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for mutable output with multiple wrap calls."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/step',
    'mutable_output',
]


def RunSteps(api: RecipeApi):
  with api.mutable_output.wrap():
    api.mutable_output(foo='bar')
  with api.mutable_output.wrap():
    api.mutable_output(baz='bop')


def GenTests(api: RecipeTestApi):

  yield api.test(
      'basic',
      api.post_check(post_process.PropertyEquals, 'foo', 'bar'),
      api.post_check(post_process.PropertyEquals, 'baz', 'bop'),
      api.post_process(post_process.DropExpectation),
  )
