# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
test_timeout.py tests that the labpack recipe module runs labpack
correctly with a timeout.
"""

from RECIPE_MODULES.chromeos.labpack.utils import catch
from PB.lab.labpack import LabpackInput

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions', 'recipe_engine/step', 'recipe_engine/path',
    'labpack'
]


def RunSteps(api):
  """RunSteps runs ensure_labpack"""
  assert isinstance(api, RecipeScriptApi), "api has wrong type: {}".format(
      repr(type(api)))

  with api.step.nest('timeout test suite') as test_suite:
    with api.step.nest('timeout argument is valid'):
      _, exn = catch(api.labpack.run_labpack, LabpackInput(), timeout=1)
      assert exn is None, str(exn)
    test_suite.step_text = 'SUCCESS'


def GenTests(api):
  """GenTests runs RunSteps and checks that the test suite as a whole succeeded."""
  assert isinstance(api, RecipeTestApi), "api has wrong type: {}".format(
      repr(type(api)))
  yield api.test(
      'basic',
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
