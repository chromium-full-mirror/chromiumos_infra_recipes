# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'paygen_orchestration',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  # Test timeout settings (includes individual runs and orch).
  api.assertions.assertEqual(
      7 * 60 * 60, api.paygen_orchestration.paygen_orchestrator_timeout_sec)


def GenTests(api: RecipeTestApi):
  yield api.test('basic', api.post_check(post_process.StatusSuccess))
