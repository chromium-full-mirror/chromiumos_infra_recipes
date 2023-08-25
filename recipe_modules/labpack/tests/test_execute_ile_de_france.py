# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
test_ensure_labpack.py tests that the labpack recipe module reports
success on the ensure_labpack step when the fake file .../labpack/labpack
exists.
"""

from recipe_engine import post_process
from PB.test_platform.skylab_test_runner.common_config import CommonConfig
from RECIPE_MODULES.chromeos.labpack.utils import to_message, make_common_config

DEPS = [
    'recipe_engine/assertions', 'recipe_engine/step', 'recipe_engine/path',
    'labpack'
]


def RunSteps(api):
  with api.step.nest('labpack test suite'):
    with api.step.nest('test convert step data method'):
      assert api.labpack.convert_step_data_to_status(
          None, 'needs_repair') == 'needs_repair'
      assert api.labpack.convert_step_data_to_status(None, 'ready') == 'ready'
    with api.step.nest('test utility methods'):
      assert to_message(4, None) == 4
      assert isinstance(to_message({}, CommonConfig()), CommonConfig)
    with api.step.nest('ready dut becomes ready'):
      assert api.labpack.execute_ile_de_france(
          common_config=make_common_config(False, None, None),
          dut_state='ready',
      ) == 'ready'
    with api.step.nest('needs repair eve becomes ready'):
      models = ['eve']
      cfg = make_common_config(True, ['eve'], None)
      assert api.labpack.get_use_ile_de_france(
          models=models,
          common_config=cfg,
      )
      out = api.labpack.execute_ile_de_france(
          dut_state='needs_repair',
          common_config=cfg,
          models=models,
          hostnames=['fake-hostname'],
      )
      assert out == 'ready', 'unexpected state: {}'.format(out)


def GenTests(api):
  """GenTests runs RunSteps and checks that the test suite as a whole succeeded."""
  yield api.test(
      'basic',
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
