# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for dirmd_update."""

from typing import Generator
from typing import Optional

from PB.recipe_engine.result import RawResult
from PB.recipes.chromeos.dirmd_update import DirmdUpdateProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/properties',
    'build_menu',
    'cros_test_plan_v2',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = DirmdUpdateProperties


def RunSteps(api: RecipeApi,
             properties: DirmdUpdateProperties) -> Optional[RawResult]:
  if not properties.table:
    raise ValueError('table must be set')

  with api.build_menu.configure_builder(
      missing_ok=True, disable_sdk=True), api.build_menu.setup_workspace():
    api.cros_test_plan_v2.dirmd_update(properties.table)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test(
      'basic',
      api.properties(table='proj.dataset.mytable'),
      api.post_process(post_process.MustRun,
                       'sync cached directory.ensure synced checkout'),
      api.post_process(
          post_process.StepCommandEquals, 'dirmd update.call test_plan', [
              '[START_DIR]/cipd/test_plan/test_plan', 'chromeos-dirmd-update',
              '-crossrcroot', '[CLEANUP]/chromiumos_workspace', '-table',
              'proj.dataset.mytable', '-loglevel', 'debug'
          ]),
  )

  yield api.test(
      'missing table',
      api.properties(table=''),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )
