# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring

from recipe_engine import post_process
from PB.recipe_modules.chromeos.siso.siso import SisoProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'siso',
]


def RunSteps(api):
  api.assertions.assertEqual(api.siso.use_siso, True)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(**{'$chromeos/siso': SisoProperties(
          use_siso=True,
      )}),
      api.post_process(post_process.DropExpectation),
  )
