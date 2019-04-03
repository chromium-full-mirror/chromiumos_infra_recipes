# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for DupIt script."""

from recipe_engine import recipe_api


class DupItApi(recipe_api.RecipeApi):
  """A module for the DupIt script."""

  def __init__(self, *args, **kwargs):
    super(DupItApi, self).__init__(*args, **kwargs)
    self._dryrun = False

  def configure(self, rsync_mirror_address, cloud_storage_uri, dryrun):
    """Configure the DupIt script module.

    Args:
      * rsync_mirror_address: the rsync mirror address that contains gentoo
        distfiles
      * cloud_storage_uri: the cloud storage URI to sync gentoo distfiles to.
      * dryrun (bool): If True, run gsutil updates in a dryrun mode.
    """
    self._dryrun = dryrun
    self._rsync_mirror_address = rsync_mirror_address
    self._cloud_storage_uri = cloud_storage_uri

  def run(self):

    local_path = self.m.path['cache'].join('builder')

    rsync_commands = [
        'rsync',
        '--recursive',  # make sure we copy files recursively
        '--links',  # symlinks are copied as symlinks
        '--safe-links',  # ignore symlinks that points to files outside
        '--perms',  # preserve files permission
        '--times',  # preserve modification times
        '--compress',  # compress files during transfer to save bandwidth
        '--stats',  # log out file-transfer stats for debugging
        '--progress',  # shows progress during transfer
        '--human-readable',
        '--timeout=180',  # IO timeout of 3 minutes
        '--bwlimit=1m',  # Rate limit so we don't DDOS the target mirror
    ]
    rsync_commands += [self.rsync_mirror_address, local_path]
    self.m.step('Sync distfiles from %s' % self.rsync_mirror_address,
                rsync_commands)

    # NOTE: we must keep the old files/objects (i.e: not passing -d) since this
    # mirror is also used by old branches which rely on the old distfiles.
    gsutil_rsync_commands = ['rsync', '-r',  # recurse
                             local_path, self.cloud_storage_uri]
    if self.dryrun:
      gsutil_rsync_commands += '-n'

    self.m.gsutil(
        cmd=gsutil_rsync_commands,
        name='Upload distfiles to %s' % self.cloud_storage_uri,
        parallel_upload=True, multithreaded=True)

  @property
  def dryrun(self):
    return self._dryrun

  @property
  def rsync_mirror_address(self):
    return self._rsync_mirror_address

  @property
  def cloud_storage_uri(self):
    return self._cloud_storage_uri
