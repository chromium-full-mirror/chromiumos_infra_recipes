# -*- coding: utf-8 -*-

# Copyright 2021 The ChromiumOS Authors
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
    'recipe_engine/step',
    'cros_history',
]



def RunSteps(api: recipe_api.RecipeApi) -> None:
  with api.step.nest('find annealing build') as presentation:
    build = api.cros_history.get_annealing_from_snapshot('fake-snapshot-id')
    if build is None:
      presentation.step_text = 'No build found'
    else:
      presentation.step_text = f'Found build (id={build.id})'


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  yield api.test(
      'get-annealing-from-snapshot',
      api.step_data('find annealing build.buildbucket.search', retcode=1),
      api.step_data('find annealing build.buildbucket.search (2)', retcode=1),
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response()],
          step_name='find annealing build.buildbucket.search (3)'),
      api.post_check(post_process.StepTextEquals, 'find annealing build',
                     'Found build (id=123)'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-annealing-build-found',
      api.buildbucket.simulated_search_results(
          [], step_name='find annealing build.buildbucket.search'),
      api.post_check(post_process.StepTextEquals, 'find annealing build',
                     'No build found'),
      api.post_process(post_process.DropExpectation),
  )
