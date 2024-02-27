# -*- coding: utf-8 -*-

# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for hours_since_breakage() function."""

from typing import Generator

from recipe_engine import post_process
from recipe_engine import recipe_test_api
from PB.recipe_modules.chromeos.cros_history.cros_history import \
  HoursSinceBreakageProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
]

PROPERTIES = HoursSinceBreakageProperties


def RunSteps(api, properties):
  result = api.cros_history.hours_since_breakage('sha1')
  expected_result = (None if properties.expected_result == 0 else
                     properties.expected_result)
  api.assertions.assertEqual(result, expected_result)


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response(end_time=0)],
          step_name='buildbucket.search'),
      api.properties(expected_result=371388),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-annealing-build-found',
      api.buildbucket.simulated_search_results([],
                                               step_name='buildbucket.search'),
      api.properties(expected_result=0),
      api.post_process(post_process.DropExpectation),
  )
