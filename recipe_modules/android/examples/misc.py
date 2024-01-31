# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties',
    'android',
]



def RunSteps(api: RecipeApi):
  api.android.get_latest_build('android-package', 'android-branch')
  api.android.write_lkgb('android-package', 'android-version', 'android-branch')


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
  yield api.test('write-lkgb-unmodified',
                 api.android.set_write_lkgb_response(modified_files=[]))
