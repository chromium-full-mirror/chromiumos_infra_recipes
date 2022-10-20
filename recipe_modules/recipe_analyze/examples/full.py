# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/assertions', 'recipe_engine/json', 'recipe_analyze']

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.assertions.assertTrue(
      api.recipe_analyze.is_recipe_affected(
          affected_files=['a/b/test.txt', 'a/foo.txt'], recipe='recipeA'))
  api.assertions.assertFalse(
      api.recipe_analyze.is_recipe_affected(
          affected_files=['a/b/test.txt', 'a/foo.txt'], recipe='recipeC'))


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'invalid-recipe',
      api.step_data(
          'recipe analyze',
          api.json.output({'invalid_recipes': ['recipeA', 'recipeB']})),
  )

  yield api.test(
      'analyze-error',
      api.step_data('recipe analyze',
                    api.json.output({'error': 'Analyze failed'})),
  )
