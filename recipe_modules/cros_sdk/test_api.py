# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""TestApi for cros_sdk."""

from recipe_engine import recipe_test_api

from PB.chromiumos import common


class CrosSdkApi(recipe_test_api.RecipeTestApi):

  @recipe_test_api.mod_test_data
  @staticmethod
  def preload_path_exists(value):
    """Returns whether to assert that the preload path exists when testing."""
    return value

  def chroot(self, use_flags=(), chrome_root=None):
    """Return a chromiumos.common.Chroot."""
    env = common.Chroot.ChrootEnv(use_flags=use_flags) if use_flags else None
    path = self.m.path.cache_dir.join('cros_chroot')
    # TODO(crbug/1215263): The Chroot() initialization can use str(path) once
    # the test_api supports str().
    abs_path = '/'.join([str(path.base)] + list(path.pieces or []))
    return common.Chroot(path='/'.join([abs_path, 'chroot']),
                         out_path='/'.join([abs_path, 'out']),
                         chrome_dir=chrome_root, env=env)
