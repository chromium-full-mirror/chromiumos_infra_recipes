# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Generator

from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'recipe_engine/buildbucket',
    'build_menu',
    'easy',
]



def RunSteps(api: recipe_api.RecipeApi) -> None:
  """Run main test logic."""
  with api.build_menu.configure_builder():
    api.easy.set_properties_step(is_staging=api.build_menu.is_staging)


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  """Generate test cases."""
  STAGING_BUCKET, CQ_BUCKET = 'staging', 'cq'
  STAGING_BUILDER, PROD_BUILDER = 'staging-amd64-generic-cq', 'amd64-generic-cq'

  for bucket in STAGING_BUCKET, CQ_BUCKET:
    for builder in STAGING_BUILDER, PROD_BUILDER:
      expect_staging = bucket == STAGING_BUCKET or builder == STAGING_BUILDER
      yield api.test(
          f'{bucket}_{builder}',
          api.buildbucket.generic_build(bucket=bucket, builder=builder),
          api.post_check(post_process.PropertyEquals, 'is_staging',
                         expect_staging),
          api.post_process(post_process.DropExpectation),
      )
