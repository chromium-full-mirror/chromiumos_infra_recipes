# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with repo repository caches.

This is mostly a wrapper around the 'repo' module.
"""

from recipe_engine import recipe_api

DEFAULT_CACHE_NAME = 'chromiumos'
DEFAULT_MANIFEST_URL = 'https://chromium.googlesource.com/chromiumos/manifest'

DEFAULT_CACHE_SYNC_OPTS = dict(
    current_branch=True,
    detach=True,
    force_sync=True,
    no_tags=True,
    jobs=32,
    optimized_fetch=True,
)


class RepoCacheApi(recipe_api.RecipeApi):
  """A module for managing repo repository caches."""

  def __init__(self, *args, **kwargs):
    super(RepoCacheApi, self).__init__(*args, **kwargs)
    self.cache_name = DEFAULT_CACHE_NAME
    self.manifest_url = DEFAULT_MANIFEST_URL

  @property
  def path(self):
    """Return the configured repo cache path."""
    return self.m.path['cache'].join(self.cache_name)

  def ensure_fresh_cache(self, init_opts=None, sync_opts=None):
    """Ensure the configured repo cache exists and is fresh.

    Args:
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
    """
    init_opts = init_opts or {}
    sync_opts = dict(DEFAULT_CACHE_SYNC_OPTS, **(sync_opts or {}))

    with self.m.step.nest('prepare repo cache'):
      self.m.file.ensure_directory('cache dir', self.path)
      with self.m.context(cwd=self.path, infra_steps=True):
        self.m.repo.init(self.manifest_url, **init_opts)
        self.m.repo.sync(**sync_opts)
