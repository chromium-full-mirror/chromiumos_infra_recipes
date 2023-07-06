# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for analyzing and retrying failed CQ runs."""

from typing import Generator
from typing import Optional

from PB.recipe_engine.result import RawResult
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = []

PYTHON_VERSION_COMPATIBILITY = 'PY3'


# pylint: disable=unused-argument
def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  pass


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test('basic',)
