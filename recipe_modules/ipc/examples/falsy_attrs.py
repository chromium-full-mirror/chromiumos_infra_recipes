# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import Generator

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi, TestData

DEPS = ['ipc']



def RunSteps(api: RecipeApi):
  api.ipc.send('topic', '/path/to/message/file', None)
  api.ipc.receive('topic', 'subscription name', None)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test('basic')
