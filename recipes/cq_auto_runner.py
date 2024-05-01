# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that opportunistically tries CQ runs on qualified CLs."""

from typing import Generator
from typing import Optional

from PB.recipe_engine.result import RawResult
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import TestData

DEPS = []


# pylint: disable=unused-argument
def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  pass


def GenTests(api: RecipeApi) -> Generator[TestData, None, None]:
  yield api.test('basic')
