# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'paygen_orchestration',
]



def RunSteps(api: RecipeApi):
  # Test timeout settings (includes individual runs and orch).
  api.assertions.assertEqual(
      9 * 60 * 60, api.paygen_orchestration.paygen_orchestrator_timeout_sec)


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
