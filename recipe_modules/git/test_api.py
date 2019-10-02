# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GitTestApi(recipe_test_api.RecipeTestApi):

  test_commit_id = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'

  @recipe_test_api.mod_test_data
  @staticmethod
  def diff_check(value):
    return value
