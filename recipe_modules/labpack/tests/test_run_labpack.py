# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
test_run_labpack.py is a smoke test for the run_labpack function.
"""

from unittest import mock

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.lab.labpack import LabpackInput
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.chromeos.labpack.utils import catch

DEPS = [
    'recipe_engine/step',
    'cros_tags',
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
    with api.step.nest('get_build'):
      _, exn = catch(api.labpack.get_build)
      assert exn is None, str(exn)
    with api.step.nest('get_dut_name'):
      with mock.patch.object(api.cros_tags, 'get_values',
                             return_value=['fake-dut']):
        hostname, exn = catch(api.labpack.get_dut_name)
        assert hostname == 'fake-dut'
        assert exn is None, str(exn)
      with mock.patch.object(api.cros_tags, 'get_values', return_value=[]):
        hostname, exn = catch(api.labpack.get_dut_name)
        assert hostname == ''
        assert exn is None, str(exn)
      with mock.patch.object(api.labpack, 'get_dut_name', return_value='a'):
        with mock.patch.object(api.labpack, 'get_build',
                               return_value=build_pb2.Build()):
          _, exn = catch(api.labpack.get_augmented_build)
          assert exn is None, str(exn)
    with api.step.nest('check running labpack multiple times'):
      api.labpack.step_count = 0
      _, _ = catch(api.labpack.run_labpack, LabpackInput(), only_run_once=True)
      res, exn = catch(api.labpack.run_labpack, LabpackInput(),
                       only_run_once=True)
      assert res is None
      assert exn is None
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
