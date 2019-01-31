# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with repo repository caches.

This is mostly a wrapper around the 'repo' module.
"""

from recipe_engine import recipe_api

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

  def ensure_fresh_cache(self, cache_path, manifest_url, init_opts=None,
                         sync_opts=None):
    """Ensure the configured repo cache exists and is fresh.

    Args:
      * cache_path (Path): Path to cache.
      * manifest_url (str): Manifest URL for 'repo.init`.
      * init_opts (dict): Extra keyword arguments to pass to 'repo.init'.
      * sync_opts (dict): Extra keyword arguments to pass to 'repo.sync'.
    """
    init_opts = init_opts or {}
    sync_opts = dict(DEFAULT_CACHE_SYNC_OPTS, **(sync_opts or {}))

    with self.m.step.nest('prepare repo cache'):
      self.m.file.ensure_directory('cache dir', cache_path)
      with self.m.context(cwd=cache_path, infra_steps=True):
        self.m.repo.init(manifest_url, **init_opts)
        self.m.repo.sync(**sync_opts)

      # Sanity check since `repo init` will happily reuse a repository in the
      # cwd's ancestor directories.
      assert self.m.path.exists(cache_path.join('.repo')), '.repo not created!'
