# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that tests a newly built SDK.

This recipe is intended to be run with a newly built SDK, to verify that it is
ready to be uprevved as the "latest SDK".

TODO(b/264564728): Add the rest of the logic.
"""

from typing import Generator

from PB.recipes.chromeos.test_new_sdk import TestNewSdkProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData


DEPS = [
    'recipe_engine/properties', 'recipe_engine/step', 'build_menu', 'cros_sdk'
]

PROPERTIES = TestNewSdkProperties


def RunSteps(api: RecipeApi, properties: TestNewSdkProperties) -> None:
  """Main recipe logic."""
  with api.step.nest('validate inputs'):
    if not properties.sdk_version:
      raise InfraFailure('No SDK version provided')
    if not properties.build_target.name:
      raise InfraFailure('No build target provided')

  with api.build_menu.configure_builder(missing_ok=True):
    with api.build_menu.setup_workspace_and_chroot(replace=True):
      api.cros_sdk('run command in chroot', ['true'])


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Define test cases."""
  yield api.test(
      'basic',
      api.properties(sdk_version='2023.03.14.159265',
                     build_target={'name': 'amd64-generic'}),
  )

  yield api.test(
      'no-version',
      api.properties(build_target={'name': 'amd64-generic'}),
      api.post_check(post_process.StepException, 'validate inputs'),
      api.post_check(post_process.SummaryMarkdown, 'No SDK version provided'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'no-build-target',
      api.properties(sdk_version='2023.03.14.159265'),
      api.post_check(post_process.StepException, 'validate inputs'),
      api.post_check(post_process.SummaryMarkdown, 'No build target provided'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
