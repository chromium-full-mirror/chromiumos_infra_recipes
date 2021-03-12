# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GitTestApi(recipe_test_api.RecipeTestApi):

  test_commit_id = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'

  def generate_test_ids(self, count):
    """Return a list of test commit IDs.

    Args:
      * count (int): The number of IDs to generate.

    Returns:
      (str) the commit id to use (varies based on index).
    """
    return ["deadbeef00000000%024x" % x for x in range(count)]

  @recipe_test_api.mod_test_data
  @staticmethod
  def diff_check(value):
    return value

  @recipe_test_api.mod_test_data
  @staticmethod
  def is_reachable(value):
    return value
