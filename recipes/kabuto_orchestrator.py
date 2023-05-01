# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Kabuto payloads and launching Kabuto shadercache jobs."""

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = ['recipe_engine/step']

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi) -> None:
  api.step('Hello World', ['echo', 'hello', 'world'])


def GenTests(api: RecipeTestApi) -> None:
  yield api.test('basic')
