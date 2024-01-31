#  -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Generator

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'git_cl',
]



def RunSteps(api: RecipeApi) -> None:
  issue_map = api.git_cl.issues()
  api.assertions.assertEqual(issue_map['refs/heads/main'], '123123')
  api.assertions.assertEqual(issue_map['refs/heads/branch'], '456456')


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test(
      'basic',
      api.git_cl.issues('', {
          'refs/heads/main': '123123',
          'refs/heads/branch': '456456'
      }),
  )
