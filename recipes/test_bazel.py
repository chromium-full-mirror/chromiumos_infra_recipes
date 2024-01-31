# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that runs Bazel tests.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from PB.chromite.api.test import BazelTestRequest
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'build_menu',
    'recipe_engine/path',
    'cros_build_api',
    'test_util',
]



def RunSteps(api: RecipeApi):
  with api.build_menu.configure_builder(), api.build_menu.setup_workspace():
    api.cros_build_api.TestService.BazelTest(
        BazelTestRequest(
            bazel_output_user_root=str(api.path['cache'].join('bazel'))),
        name='run bazel tests')


def GenTests(api: RecipeTestApi):
  yield api.test(
      'snapshot',
      api.test_util.test_child_build(None, builder='bazel-test-snapshot').build)
