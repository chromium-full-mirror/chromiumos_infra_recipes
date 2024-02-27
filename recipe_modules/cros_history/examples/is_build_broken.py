# -*- coding: utf-8 -*-

# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for is_build_broken() function."""

from typing import Generator

from recipe_engine import post_process
from recipe_engine import recipe_test_api
from PB.recipe_modules.chromeos.cros_history.cros_history import \
  IsBuildBrokenProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
]

PROPERTIES = IsBuildBrokenProperties


def RunSteps(api, properties):
  result = api.cros_history.is_build_broken('sha1', 'sha2')
  api.assertions.assertEqual(result, properties.expected_result)


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  yield api.test(
      'build-is-not-broken',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response(end_time=1)],
          step_name='check if build is broken.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response(end_time=3)],
          step_name='check if build is broken.buildbucket.search (2)'),
      api.properties(expected_result=False),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'build-is-broken',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response(end_time=5)],
          step_name='check if build is broken.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response(end_time=3)],
          step_name='check if build is broken.buildbucket.search (2)'),
      api.properties(expected_result=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-annealing-build-found-1',
      api.buildbucket.simulated_search_results(
          [], step_name='check if build is broken.buildbucket.search'),
      api.properties(expected_result=True),
      api.post_process(post_process.DropExpectation),
  )
