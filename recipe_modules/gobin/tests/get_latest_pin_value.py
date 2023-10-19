# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for get_latest_pin_value."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'gobin',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  api.gobin.get_latest_pin_value('deadbeef')


def GenTests(api):
  yield api.test(
      'no-ancestry',
      # deadbeef is not an ancestor of HEAD!
      api.step_data('get commits since deadbeef',
                    stdout=api.raw_io.output_text('')),
      api.post_process(post_process.DropExpectation),
      status='FAILURE')
