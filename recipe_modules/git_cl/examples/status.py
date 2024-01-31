# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
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
    'git_cl',
]



def RunSteps(api: RecipeApi) -> None:
  output = api.git_cl.status(field='url', fast=True, issue='3402394',
                             step_name='git cl status')
  api.assertions.assertEqual(output, b'foo')


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test(
      'basic',
      api.git_cl.output('git cl status', 'foo'),
  )
