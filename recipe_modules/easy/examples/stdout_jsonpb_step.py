# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf.wrappers_pb2 import Int32Value

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'easy',
]



def RunSteps(api: RecipeApi):
  out = api.easy.stdout_jsonpb_step('foo', ['foo'], Int32Value)
  api.assertions.assertEqual(out.value, 1)


def GenTests(api: RecipeTestApi):
  yield api.test('basic',
                 api.easy.simulate_jsonpb_step('foo', Int32Value(value=1)))
