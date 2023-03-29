# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that uprev_sdk() creates local uprev commits as expected."""

from typing import Generator

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'pupr_local_uprev',
]


def RunSteps(api: RecipeApi):
  """Main test case logic."""
  api.pupr_local_uprev.uprev_sdk()


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Specific test cases on uprev_sdk().

  TODO(b/259445565): Once uprev_sdk() has been implemented, flesh this out.
  """
  yield api.test(
      'basic',
      api.post_check(post_process.StepException, 'uprev sdk'),
      status='INFRA_FAILURE',
  )
