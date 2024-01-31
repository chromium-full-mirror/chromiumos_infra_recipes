# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Example of how to define a test cases with a custom builder config."""

from typing import Generator

from PB.chromiumos.builder_config import BuilderConfig
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'cros_infra_config',
    'easy',
]



def RunSteps(api: RecipeApi) -> None:
  """Configure the builder, and then log some properties.

  The test cases are expected to make assertions on the properties via
  post_process checks.
  """
  config = api.cros_infra_config.configure_builder()
  api.easy.set_properties_step(
      builder=api.buildbucket.build.builder.builder,
      bucket=api.buildbucket.build.builder.bucket,
      run_unit_tests=config.unit_tests.ebuilds_run_spec,
  )


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Generate test cases for full coverage of use_custom_builder_configs()."""
  yield api.test(
      'default-builder-override-value',
      api.cros_infra_config.use_custom_builder_config(
          BuilderConfig(
              unit_tests=BuilderConfig.UnitTests(
                  ebuilds_run_spec=BuilderConfig.RunSpec.RUN,
              )),
          step_name='configure builder',
      ),
      api.post_check(post_process.PropertyEquals, 'builder', 'custom-builder'),
      api.post_check(post_process.PropertyEquals, 'run_unit_tests', 2),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'override-builder',
      api.cros_infra_config.use_custom_builder_config(
          BuilderConfig(
              id=BuilderConfig.Id(
                  name='my-cool-builder',
                  bucket='my-cool-bucket',
              ), unit_tests=BuilderConfig.UnitTests(
                  ebuilds_run_spec=BuilderConfig.RunSpec.RUN,
              )),
          step_name='configure builder',
      ),
      api.post_check(post_process.PropertyEquals, 'builder', 'my-cool-builder'),
      api.post_check(post_process.PropertyEquals, 'bucket', 'my-cool-bucket'),
      api.post_check(post_process.PropertyEquals, 'run_unit_tests', 2),
      api.post_process(post_process.DropExpectation),
  )
