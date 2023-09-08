# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
test_run_labpack.py is a smoke test for the run_labpack function.
"""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from PB.lab.labpack import LabpackInput
from RECIPE_MODULES.chromeos.labpack.utils import catch

DEPS = [
    'recipe_engine/step',
    'easy',
    'labpack',
]


def RunSteps(api):
  """RunSteps runs ensure_labpack"""
  assert isinstance(api, RecipeScriptApi), 'api has wrong type: {}'.format(
      repr(type(api)))
  with api.step.nest('run labpack test suite') as test_suite:
    with api.step.nest('run_labpack fails with not_implemented error'):
      _, exn = catch(api.labpack.run_labpack, LabpackInput())
      assert exn is None, str(exn)
    with api.step.nest('_get_build'):
      _, exn = catch(api.labpack._get_build)
      assert exn is None, str(exn)
    test_suite.step_text = 'SUCCESS'


def GenTests(api):
  """GenTests runs RunSteps and checks that the test suite as a whole succeeded."""
  assert isinstance(api, RecipeTestApi), 'api has wrong type: {}'.format(
      repr(type(api)))
  yield api.test(
      'basic',
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
