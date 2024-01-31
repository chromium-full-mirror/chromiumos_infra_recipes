# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Generator

from PB.recipe_modules.chromeos.recipe_analyze.tests import (
    is_recipe_affected as is_recipe_affected_pb2)
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_analyze',
]


PROPERTIES = is_recipe_affected_pb2.IsRecipeAffectedProperties


def RunSteps(
    api: recipe_api.RecipeApi,
    properties: is_recipe_affected_pb2.IsRecipeAffectedProperties) -> None:
  """Main test logic.

  Run is_recipe_affected on the affected_files, and assert that each expected
  affectedrecipe is indeed affected, and that each expected unaffectedrecipe
  is unaffected.
  """
  # First, just run is_recipe_affected(). This covers situations where no
  # recipes are expected or unexpected.
  api.recipe_analyze.is_recipe_affected(
      affected_files=properties.affected_files,
      recipe='',
  )

  for expected_affected_recipe in properties.expected_affected_recipes:
    api.assertions.assertTrue(
        api.recipe_analyze.is_recipe_affected(
            affected_files=properties.affected_files,
            recipe=expected_affected_recipe))

  for expected_unaffected_recipe in properties.expected_unaffected_recipes:
    api.assertions.assertFalse(
        api.recipe_analyze.is_recipe_affected(
            affected_files=properties.affected_files,
            recipe=expected_unaffected_recipe))


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  """Generate test cases."""
  yield api.test(
      'basic',
      api.properties(
          is_recipe_affected_pb2.IsRecipeAffectedProperties(
              affected_files=['a/b/test.txt', 'a/foo.txt'],
              expected_affected_recipes=['recipeA'],
              expected_unaffected_recipes=['recipeC'],
          ),
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'invalid-recipe',
      api.properties(
          is_recipe_affected_pb2.IsRecipeAffectedProperties(
              affected_files=['a/b/test.txt', 'a/foo.txt'],
          ),
      ),
      api.step_data(
          'recipe analyze',
          api.json.output({'invalid_recipes': ['recipeA', 'recipeB']}),
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'analyze-error',
      api.properties(
          is_recipe_affected_pb2.IsRecipeAffectedProperties(
              affected_files=['a/b/test.txt', 'a/foo.txt'],
          ),
      ),
      api.step_data(
          'recipe analyze',
          api.json.output({'error': 'Analyze failed'}),
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  _EXAMPLE_FILE = 'recipe_modules/a/examples/foo.txt'
  _TEST_FILE = '~/chromiumos/infra/recipes/recipe_modules/b/tests/bar.txt'
  yield api.test(
      'filter-out-examples-and-tests',
      api.properties(
          is_recipe_affected_pb2.IsRecipeAffectedProperties(
              affected_files=[
                  'a/b/test.txt',
                  _EXAMPLE_FILE,
                  _TEST_FILE,
                  'a/foo.txt',
              ],
          )),
      api.post_check(
          post_process.StepCommandContains,
          'recipe analyze',
          '{"files": ["a/b/test.txt", "a/foo.txt"], "recipes": [""]}',
      ),
      api.post_process(post_process.DropExpectation),
  )
