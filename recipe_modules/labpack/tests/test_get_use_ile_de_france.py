# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
test_run_labpack.py is a smoke test for the run_labpack function.
"""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/step',
    'easy',
    'labpack',
]


def RunSteps(api):
  with api.step.nest('get_use_ile_de_france test suite'):
    assert api.labpack.get_use_ile_de_france(models=[],
                                             ile_de_france_config=None) is False


def GenTests(api):
  """GenTests runs RunSteps and checks that the test suite as a whole succeeded."""
  yield api.test(
      'basic',
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
