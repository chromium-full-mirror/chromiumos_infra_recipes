# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the method that reads the remote latest SDK file."""

from typing import Generator

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData
from RECIPE_MODULES.chromeos.cros_sdk.api import LATEST_SDK_KEY
from RECIPE_MODULES.chromeos.cros_sdk.api import LATEST_UPREV_TARGET_KEY

DEPS = [
    'recipe_engine/assertions',
    'cros_sdk',
    'key_value_store',
]


def RunSteps(api: RecipeApi):
  """Main test logic."""
  contents = api.cros_sdk.read_remote_latest_sdk_file()
  parsed = api.key_value_store.parse_contents(contents)
  api.assertions.assertEqual(parsed[LATEST_SDK_KEY], '2023.03.13.222421')
  api.assertions.assertEqual(parsed[LATEST_UPREV_TARGET_KEY],
                             '2023.03.14.159265')


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Define test cases."""
  yield api.test('basic', api.post_process(post_process.DropExpectation))
