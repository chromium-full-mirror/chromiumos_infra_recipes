# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class SyncChromeApi(recipe_api.RecipeApi):

  @property
  def cache_path(self):
    """ The path to use for gclient caching.

    All git repos are cached here, and it is used for clones, instead of cloning
    directly from the remote.
    """
    return self.m.path['cache'].join('chrome')

  def sync_chrome(self, chrome_root):
    """
    Sync Chrome source code.

    Must be run with cwd inside a chromiumos source root.

    Args:
      chrome_root (str): Directory to sync the Chrome source code to.
    """
    # TODO(crbug.com/945606): Call sync_chrome in build_target recipe.
    # portageq must be run with cwd inside a chromiumos source root.
    revision = self.m.portage.portageq_best_visible_version(
        'chromeos-base/chromeos-chrome')

    self.m.file.ensure_directory('ensure chrome cache', self.cache_path)
    self.m.file.ensure_directory('ensure chrome root', chrome_root)
    with self.m.context(cwd=chrome_root):
      cfg = self.m.gclient.make_config(CACHE_DIR=self.cache_path)
      soln = cfg.solutions.add()
      soln.name = 'src'
      soln.url = 'https://chromium.googlesource.com/chromium/src.git'
      soln.revision = revision
      # TODO(chromium:945606): Read chrome_internal from infra_config and add
      # internal checkout.

      self.m.gclient.checkout(gclient_config=cfg)
