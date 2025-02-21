# -*- coding: utf-8 -*-
# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for mutable output with nested wrap calls."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'mutable_output',
]


def RunSteps(api: RecipeApi):
  with api.mutable_output.wrap():
    with api.mutable_output.wrap():
      # Explicitly omit coverage because we expect the context above this to
      # raise an exception, but we need to have something in here for python
      # indenting rules...
      api.mutable_output(foo='baz', third='yet another?')  # pragma: no cover


def GenTests(api: RecipeTestApi):

  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
