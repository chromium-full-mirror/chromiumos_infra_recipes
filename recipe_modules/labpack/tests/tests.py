# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = ['recipe_engine/assertions', 'recipe_engine/step', 'labpack']


def RunSteps(api):
  """RunSteps runs the whole test suite."""
  assert isinstance(api, RecipeScriptApi), "api has wrong type: {}".format(
      repr(type(api)))
  with api.step.nest('labpack test suite') as test_suite:
    assert api.labpack, 'labpack API must be truthy'
    test_suite.step_text = 'SUCCESS'


def GenTests(api):
  """GenTests runs RunSteps and checks that the test suite as a whole succeeded."""
  assert isinstance(api, RecipeTestApi), "api has wrong type: {}".format(
      repr(type(api)))
  yield api.test(
      'basic',
      api.post_check(post_process.StepTextEquals, 'labpack test suite',
                     'SUCCESS'),
      api.post_process(post_process.DropExpectation),
  )
