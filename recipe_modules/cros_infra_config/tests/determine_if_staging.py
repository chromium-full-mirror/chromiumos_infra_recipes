# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Generator

from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'cros_infra_config',
    'easy',
]



def RunSteps(api: recipe_api.RecipeApi) -> None:
  """Main test logic."""
  api.cros_infra_config.determine_if_staging()
  api.easy.set_properties_step(is_staging=api.cros_infra_config.is_staging)


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  """Create test cases."""

  yield api.test(
      'staging-bucket', api.buildbucket.generic_build(bucket='staging'),
      api.post_check(post_process.PropertyEquals, 'is_staging', True),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'staging-shadow-bucket',
      api.buildbucket.generic_build(bucket='staging.shadow'),
      api.post_check(post_process.PropertyEquals, 'is_staging', True),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'staging-builder',
      api.buildbucket.generic_build(builder='staging-sign-image'),
      api.post_check(post_process.PropertyEquals, 'is_staging', True),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'generic-builder', api.buildbucket.generic_build(),
      api.post_check(post_process.PropertyEquals, 'is_staging', False),
      api.post_process(post_process.DropExpectation))
