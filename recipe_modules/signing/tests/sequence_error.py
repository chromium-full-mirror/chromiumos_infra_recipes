# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that wait_for_signing is required before retrieving signed build
metadata."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'signing',
]



def RunSteps(api: RecipeApi):
  with api.assertions.assertRaises(api.step.StepFailure):
    api.signing.get_signed_build_metadata(None)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'fails-when-get_signed_build_metadata-is-called-first',
      api.post_check(post_process.DoesNotRun, 'parse metadata'),
      api.post_process(post_process.DropExpectation),
  )
