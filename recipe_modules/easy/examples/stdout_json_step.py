# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'easy',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  json_stdout = api.easy.stdout_json_step('json', ['ls'],
                                          ignore_exceptions=True)
  api.assertions.assertDictEqual(json_stdout, {'b': 2})


def GenTests(api: RecipeTestApi):
  yield api.test('basic', api.easy.simulate_json_step('json', {'b': 2}))
