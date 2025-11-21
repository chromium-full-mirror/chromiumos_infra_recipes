# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring

from typing import Generator

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'cros_source',
    'workspace_util',
]


def RunSteps(api: RecipeApi) -> None:
  api.cros_source.configure_builder()
  with api.workspace_util.setup_workspace(), \
      api.workspace_util.sync_to_commit(groups=['default']):
    pass


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          git_ref='refs/heads/release-R90-13816.B',
          revision='1234567890123456789012345678901234567890',
      ),
      api.post_process(
          post_process.StepCommandContains,
          'ensure synced checkout.repo init',
          ['--groups', 'default'],
      ),
      api.post_process(post_process.DropExpectation),
  )
