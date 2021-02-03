# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for LvfsMirror script."""

from recipe_engine import recipe_api


class LvfsMirror(recipe_api.RecipeApi):
  """A module for the LvfsMirror script."""

  def __init__(self, *args, **kwargs):
    super(LvfsMirror, self).__init__(*args, **kwargs)

  def configure(self, mirror_address):
    """Configure the LvfsMirror script module.

    Args:
      * mirror_address: The mirror address for the LVFS repository.
    """
    self._mirror_address = mirror_address
    self._local_cache = self.m.path['cache'].join('lvfs')

  def run(self):
    self.m.file.ensure_directory('ensure_local_cache', self.local_cache)
    self.m.python('run sync-pulp.py', self.resource('sync-pulp.py'),
                  args=[self.mirror_address, self.local_cache])

  @property
  def mirror_address(self):
    return self._mirror_address

  @property
  def local_cache(self):
    return self._local_cache
