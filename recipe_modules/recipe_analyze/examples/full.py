# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/assertions', 'recipe_engine/json', 'recipe_analyze']


def RunSteps(api):
  api.assertions.assertTrue(
      api.recipe_analyze.is_recipe_affected(
          affected_files=['a/b/test.txt', 'a/foo.txt'], recipe='recipeA'))
  api.assertions.assertFalse(
      api.recipe_analyze.is_recipe_affected(
          affected_files=['a/b/test.txt', 'a/foo.txt'], recipe='recipeC'))


def GenTests(api):
  yield api.test('basic')

  yield (api.test('invalid_recipe') +  #
         api.step_data(
             'recipe analyze',
             api.json.output({
                 'invalid_recipes': ['recipeA', 'recipeB']
             })))

  yield (api.test('analyze_error') +  #
         api.step_data('recipe analyze',
                       api.json.output({
                           'error': 'Analyze failed'
                       })))
