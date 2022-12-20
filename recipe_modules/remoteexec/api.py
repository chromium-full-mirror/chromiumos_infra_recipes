# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with re-client for remote execution."""

from recipe_engine import recipe_api


class RemoteexecApi(recipe_api.RecipeApi):
  """A module for working with re-client for remote execution."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._reclient_version = properties.reclient_version
    self._reproxy_cfg_file = properties.reproxy_cfg_file
    self._reclient_dir = None

  @property
  def reclient_dir(self):
    """Fetches the reclient directory and returns its path."""
    if self._reclient_dir is None:
      self._ensure_reclient()
    return self._reclient_dir

  @property
  def reproxy_cfg_file(self):
    return self._reproxy_cfg_file

  def _ensure_reclient(self):
    with self.m.step.nest('ensure reclient binaries'), self.m.context(
        infra_steps=True):
      reclient_dir = self.m.path['start_dir'].join('cipd', 'rbe')
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('infra/rbe/client/${platform}',
                       str(self._reclient_version))
      self.m.cipd.ensure(reclient_dir, pkgs)
      self._reclient_dir = reclient_dir
