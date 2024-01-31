# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi, StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'conductor',
]



def RunSteps(api: RecipeApi):
  with api.assertions.assertRaises(StepFailure):
    api.conductor.collect('child builds', [], step_name='conductor collect')


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/conductor': {
                  'enable_conductor': True,
                  'collect_configs': {
                      'child builds': {
                          'rules': [{
                              'cutoff_seconds': 1,
                          },],
                      },
                  },
              },
          }),
      api.post_process(post_process.DropExpectation),
  )
