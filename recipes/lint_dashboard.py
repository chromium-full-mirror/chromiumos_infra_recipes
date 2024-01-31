# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for uploading linting data for use in the Code Health Dashboard."""

import json
import time
from typing import Generator
from typing import List
from typing import Optional

from PB.chromite.api.toolchain import LinterFinding
from PB.chromite.api.toolchain import DashboardLintRequest
from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_engine.result import RawResult
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
]



def _CollectLints(api: RecipeApi) -> List[LinterFinding]:
  """Emerges affected packages and retrieves generated lints."""
  with api.step.nest('Collecting Lints for Dashboard'):
    test_data = json.dumps({'gs_path': 'fake-gs-path'})

    return api.cros_build_api.ToolchainService.EmergeAndUploadLints(
        DashboardLintRequest(sysroot=api.build_menu.sysroot,
                             chroot=api.build_menu.chroot,
                             start_time=round(time.time())),
        test_output_data=test_data)


def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  with api.build_menu.configure_builder(missing_ok=True) as config:
    with api.build_menu.setup_workspace_and_chroot():
      return DoRunSteps(api, config)


def DoRunSteps(api: RecipeApi, config: BuilderConfig) -> Optional[RawResult]:
  api.build_menu.setup_sysroot_and_determine_relevance()
  api.build_menu.bootstrap_sysroot(config)
  _CollectLints(api)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  yield api.build_menu.test(
      'normal', api.post_check(post_process.StepSuccess, 'configure builder'),
      api.post_check(post_process.StepSuccess,
                     'Collecting Lints for Dashboard'),
      api.post_process(post_process.DropExpectation), build_target='atlas',
      status='SUCCESS')

  yield api.build_menu.test(
      'build-api-failure',
      api.post_check(post_process.StepSuccess, 'configure builder'),
      api.post_check(post_process.StepFailure,
                     'Collecting Lints for Dashboard'),
      api.build_menu.set_build_api_return(
          'Collecting Lints for Dashboard',
          'ToolchainService/EmergeAndUploadLints', retcode=1),
      api.post_process(post_process.DropExpectation),
      build_target='atlas',
      status='FAILURE',
  )
