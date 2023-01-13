# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi, StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'conductor',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  api.assertions.assertIsNone(api.conductor.collect_config('child builds'))

  with api.assertions.assertRaises(StepFailure):
    api.conductor.collect('child builds', [], step_name='conductor collect')


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(**{
          '$chromeos/conductor': {
              'enable_conductor': True,
          },
      }),
      api.post_process(post_process.DropExpectation),
  )
