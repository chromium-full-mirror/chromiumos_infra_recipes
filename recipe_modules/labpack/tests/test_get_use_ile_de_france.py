# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
test_run_labpack.py is a smoke test for the run_labpack function.
"""

from recipe_engine import post_process
from RECIPE_MODULES.chromeos.labpack.utils import make_common_config

DEPS = [
    'recipe_engine/step',
    'easy',
    'labpack',
]


def RunSteps(api):
  with api.step.nest('get_use_ile_de_france test suite'):
    with api.step.nest('default case'):
      assert api.labpack.get_use_ile_de_france(models=[],
                                               common_config=None) is False
    with api.step.nest('opted-in model'):
      assert api.labpack.get_use_ile_de_france(
          models=["eve"], common_config=make_common_config(True, ["eve"],
                                                           None)) is True
    with api.step.nest('opted-out model'):
      assert api.labpack.get_use_ile_de_france(
          models=["eve"], common_config=make_common_config(True, None,
                                                           ["eve"])) is False


def GenTests(api):
  """GenTests runs RunSteps and checks that the test suite as a whole succeeded."""
  yield api.test(
      'basic',
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
