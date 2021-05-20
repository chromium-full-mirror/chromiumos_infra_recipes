# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.chromiumos import common


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

  def chroot(self, use_flags=(), chrome_root=None):
    """Return a chromiumos.common.Chroot."""
    env = common.Chroot.ChrootEnv(use_flags=use_flags) if use_flags else None
    chroot_path = self.m.path['cache'].join('cros_chroot', 'chroot')
    # TODO(crbug/1215263): The Chroot() initialization can use str(chroot_path)
    # once the test_api supports str().
    abs_path = '/'.join([str(chroot_path.base)] +
                        list(chroot_path.pieces or []))
    return common.Chroot(path=abs_path, chrome_dir=chrome_root, env=env)
