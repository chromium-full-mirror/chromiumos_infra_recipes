# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify signing_utils.any_empty method."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'signing_utils',
]



def RunSteps(api: RecipeApi):
  instructions = api.properties['instructions']
  expected_any_empty = api.properties['expected_any_empty']

  any_empty = api.signing_utils.any_empty(instructions)

  api.assertions.assertEqual(expected_any_empty, any_empty)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'empty-insns',
      api.properties(instructions={
          'insns1': None,
      }, expected_any_empty=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'partial-insns',
      api.properties(
          instructions={
              'insns1': 'foo',
              'insns2': None,
              'insns3': 'baz',
          }, expected_any_empty=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'complete-insns',
      api.properties(
          instructions={
              'insns1': 'foo',
              'insns2': 'bar',
              'insns3': 'baz',
          }, expected_any_empty=False),
      api.post_process(post_process.DropExpectation),
  )
