# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class SyncChromeApi(recipe_api.RecipeApi):

  def sync_chrome(self, chrome_root):
    """
    Sync Chrome source code.

    Args:
      chrome_root (str): Directory to sync the Chrome source code to.
    """
    cfg = self.m.gclient.make_config(CACHE_DIR=chrome_root)
    soln = cfg.solutions.add()
    soln.name = 'src'
    soln.url = 'https://chromium.googlesource.com/chromium/src.git'
    soln.revision = self.m.portage.portageq_best_visible_version(
        'chromeos-base/chromeos-chrome')
    # TODO(chromium:945606): Read chrome_internal from infra_config and add
    # internal checkout.

    self.m.gclient.checkout(gclient_config=cfg)
