# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Generator

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'gcloud',
]



def RunSteps(api: RecipeApi):
  api.gcloud.create_image_from_disk('image-123', 'chromeos', 'us-central1-b')


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  yield api.test(
      'disk-exists-swallowed',
      api.step_data(
          'create image from disk', stdout=api.raw_io.output(
              'Some non-sequitur message to disk existing.\n'
              "The resource 'a/big/resource/thing' already exists"),
          retcode=404),
      api.post_check(post_process.DoesNotRun, 'create image from disk (2)'),
      api.post_check(post_process.DropExpectation),
  )

  yield api.test(
      'other-error-not-swallowed',
      api.step_data(
          'create image from disk', stdout=api.raw_io.output(
              'Some non-sequitur message to disk existing.\n'
              'some other bad error'), retcode=404),
      api.post_check(post_process.MustRun, 'create image from disk (2)'),
      api.post_check(post_process.DropExpectation),
  )
