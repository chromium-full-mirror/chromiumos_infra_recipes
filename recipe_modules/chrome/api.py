# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

from PB.chromite.api import packages

CHROMIUM_CACHE_DIR = '/preload/chrome_cache'


class ChromeApi(recipe_api.RecipeApi):

  def sync(self, chrome_root):
    """
    Sync Chrome source code.

    Must be run with cwd inside a chromiumos source root.

    Args:
      chrome_root (str): Directory to sync the Chrome source code to.
    """
    # TODO(crbug.com/945606): Call sync_chrome in build_target recipe.
    # portageq must be run with cwd inside a chromiumos source root.
    request = packages.GetBestVisibleRequest(
        atom='chromeos-base/chromeos-chrome')
    revision = self.m.cros_build_api.PackageService.GetBestVisible(
        request, infra_step=True).package_info.version

    self.m.file.ensure_directory('ensure chrome root', chrome_root)
    with self.m.context(cwd=chrome_root):
      cfg = self.m.gclient.make_config(CACHE_DIR=CHROMIUM_CACHE_DIR)
      soln = cfg.solutions.add()
      soln.name = 'src'
      soln.url = 'https://chromium.googlesource.com/chromium/src.git'
      soln.revision = revision
      # TODO(chromium:945606): Read chrome_internal from infra_config and add
      # internal checkout.

      self.m.gclient.checkout(gclient_config=cfg)
