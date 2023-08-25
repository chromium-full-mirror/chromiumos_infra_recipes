# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
test_ensure_labpack.py tests that the labpack recipe module reports
success on the ensure_labpack step when the fake file .../labpack/labpack
exists.
"""

from RECIPE_MODULES.chromeos.labpack.result_map import add_assertion_to_map
from RECIPE_MODULES.chromeos.labpack.result_map import new_result_map

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions', 'recipe_engine/step', 'recipe_engine/path',
    'labpack'
]


def RunSteps(api):
  """RunSteps runs ensure_labpack"""
  assert isinstance(api, RecipeScriptApi), 'api has wrong type: {}'.format(
      repr(type(api)))
  with api.step.nest('labpack test suite') as test_suite:
    with api.step.nest('ensure labpack succeeds'):
      # Add a fake labpack executable at the expected location for testing purposes.
      api.path.mock_add_file(api.labpack.get_cipd_path().join('labpack'))
      assert api.path.exists(
          api.labpack.get_cipd_path().join('labpack')
      ), 'Test MUST create a labpack file, otherwise the test is pointless'
      assert api.labpack.ensure_labpack()
    with api.step.nest('test helper functions'):
      assert new_result_map() == {
          'ok': True,
          'msg': None
      }, 'New_result_map should return empty map'
      assert add_assertion_to_map(new_result_map(), True, 'a') == {
          'ok': True,
          'msg': None
      }, 'True assertion should not change message'
      assert add_assertion_to_map(
          new_result_map(),
          False,
          '83f9fc6c-d68a-4f97-9f4e-d1c95c76b0e7',
      ) == {
          'ok': False,
          'msg': '83f9fc6c-d68a-4f97-9f4e-d1c95c76b0e7'
      }, 'False assertion should change message'
    test_suite.step_text = 'SUCCESS'


def GenTests(api):
  """GenTests runs RunSteps and checks that the test suite as a whole succeeded."""
  assert isinstance(api, RecipeTestApi), 'api has wrong type: {}'.format(
      repr(type(api)))
  yield api.test(
      'basic',
      api.post_check(post_process.StepTextEquals, 'labpack test suite',
                     'SUCCESS'),
      api.post_process(post_process.DropExpectation),
  )
