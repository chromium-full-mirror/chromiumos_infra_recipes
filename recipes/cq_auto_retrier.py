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

DEPS = [
    'auto_retry_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  _ = api.auto_retry_util.cq_retry_candidates()


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test('basic',)
