# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for LvfsMirror script."""

from recipe_engine import recipe_api


class LvfsMirror(recipe_api.RecipeApi):
  """A module for the LvfsMirror script."""

  def configure(self, mirror_address, gs_uri):
    """Configure the LvfsMirror script module.

    Args:
      * mirror_address: The mirror address for the LVFS repository.
    """
    self._mirror_address = mirror_address
    self._gs_uri = gs_uri
    self._local_cache = self.m.path.cache_dir / 'lvfs'

  def _get_list_of_gs_files(self):
    """Get list of file paths from Google Storage bucket"""
    gsutil_ls_cmd = ['ls', '-r', self.m.path.join(self.gs_uri, '*.cab')]
    gs_file_list_path = self.m.path.cache_dir / 'gs.txt'
    gsutil_ls_stdout = self.m.raw_io.output_text(leak_to=gs_file_list_path)
    self.m.gsutil(cmd=gsutil_ls_cmd, name='List files in %s' % self.gs_uri,
                  stdout=gsutil_ls_stdout)
    return gs_file_list_path

  def _rsync_to_gs(self):
    # Recursively sync all files to gs_uri.
    gsutil_rsync_cmd = [
        'rsync',
        '-r',
        # All files are public-read.
        '-a',
        'public-read',
        self.local_cache,
        self.gs_uri,
    ]
    self.m.gsutil(cmd=gsutil_rsync_cmd, name='Sync to %s' % self.gs_uri,
                  parallel_upload=True, multithreaded=True)

  def run(self):
    self.m.file.ensure_directory('ensure_local_cache', self.local_cache)
    gs_file = self._get_list_of_gs_files()
    # sync-pulp.py will update local copy with any new files.
    # We provide the list of existent files on the third argument to
    # avoid failures due to file changes referenced from any existing
    # repository manifest that we pinned to a given OS release.
    self.m.step('run sync-pulp.py', [
        'vpython3',
        self.resource('sync-pulp.py'), self.mirror_address, self.local_cache,
        gs_file
    ])
    self._rsync_to_gs()

  @property
  def mirror_address(self):
    return self._mirror_address

  @property
  def gs_uri(self):
    return self._gs_uri

  @property
  def local_cache(self):
    return self._local_cache
