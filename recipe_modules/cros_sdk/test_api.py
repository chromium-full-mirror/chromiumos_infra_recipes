# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CrosSdkApi(recipe_test_api.RecipeTestApi):

  @recipe_test_api.mod_test_data
  @staticmethod
  def is_chroot_usable(values):
    """Returns a list of return values for _is_chroot_usable when testing."""
    return values

  @recipe_test_api.mod_test_data
  @staticmethod
  def preload_path_exists(value):
    """Returns whether to assert that the preload path exists when testing."""
    return value
