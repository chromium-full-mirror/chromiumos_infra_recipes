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
    'git_cl',
]



def RunSteps(api: RecipeApi) -> None:
  api.git_cl.get_description(patch_url='foo')


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test(
      'basic',
  )
