# -*- coding: utf-8 -*-
# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for mutable output."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/step',
    'mutable_output',
]


def RunSteps(api: RecipeApi):
  with api.mutable_output.wrap():
    with api.step.nest('Inner step'):
      api.mutable_output(foo='bar', other=2)
    api.mutable_output(foo='baz', third='yet another?')


def GenTests(api: RecipeTestApi):

  yield api.test(
      'basic',
      api.post_check(post_process.PropertyEquals, 'foo', 'baz'),
      api.post_check(post_process.PropertyEquals, 'other', 2),
      api.post_check(post_process.PropertyEquals, 'third', 'yet another?'),
      api.post_process(post_process.DropExpectation),
  )
