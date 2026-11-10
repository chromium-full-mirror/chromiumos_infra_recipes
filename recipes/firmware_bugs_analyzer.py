# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that resolves tracked ChromeOS firmware regressions in Spanner."""

from typing import Generator

from PB.recipes.chromeos.firmware_bugs_analyzer import (
    FirmwareBugsAnalyzerProperties,)
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = FirmwareBugsAnalyzerProperties

_CIPD_PACKAGE = 'chromiumos/infra/fw-bugs/${platform}'
_ANALYZE_TIMEOUT_SECONDS = 25 * 60


def RunSteps(api: RecipeApi,
             properties: FirmwareBugsAnalyzerProperties) -> None:
  """Installs fw-bugs from CIPD and resolves pending firmware regressions.

  Args:
    api: Recipe engine API handle.
    properties: Input properties configuring CIPD version and target database.
  """
  cipd_ref = properties.cipd_ref or 'latest'
  install_dir = api.path.start_dir / 'cipd' / 'fw-bugs'

  with api.context(infra_steps=True):
    ensure_file = api.cipd.EnsureFile()
    ensure_file.add_package(_CIPD_PACKAGE, cipd_ref)
    api.cipd.ensure(install_dir, ensure_file)

  cmd = [install_dir / 'fw-bugs', 'analyze']
  if properties.staging:
    cmd.append('-staging')
  if properties.regression_id > 0:
    cmd.extend(['-id', str(properties.regression_id)])
  if properties.force:
    cmd.append('-force')

  api.step(
      'analyze firmware regressions',
      cmd,
      timeout=_ANALYZE_TIMEOUT_SECONDS,
  )


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Generates recipe simulation test cases for firmware_bugs_analyzer.

  Args:
    api: Recipe test API handle.

  Yields:
    TestData instances covering production, staging, and targeted runs.
  """
  yield api.test(
      'prod_default',
      api.properties(FirmwareBugsAnalyzerProperties()),
      api.post_process(
          post_process.StepCommandEquals,
          'analyze firmware regressions',
          ['[START_DIR]/cipd/fw-bugs/fw-bugs', 'analyze'],
      ),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging_targeted_force',
      api.properties(
          FirmwareBugsAnalyzerProperties(
              cipd_ref='git_revision:deadbeef',
              staging=True,
              regression_id=42,
              force=True,
          )),
      api.post_process(
          post_process.StepCommandEquals,
          'analyze firmware regressions',
          [
              '[START_DIR]/cipd/fw-bugs/fw-bugs',
              'analyze',
              '-staging',
              '-id',
              '42',
              '-force',
          ],
      ),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
