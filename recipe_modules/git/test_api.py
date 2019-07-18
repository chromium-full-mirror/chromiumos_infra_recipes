# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GitTestApi(recipe_test_api.RecipeTestApi):

  test_commit_id = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'

  @property
  def test_repository_root(self):
    return self.m.path['start_dir'].join('git_repository')
