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

  def configure(self, rsync_mirror_address, rsync_mirror_rate_limit,
                cloud_storage_uri, dryrun):
    """Configure the DupIt script module.

    Args:
      * rsync_mirror_address: the rsync mirror address that contains gentoo
        distfiles
      * rsync_mirror_rate_limit: the rate limit of syncing from public mirror.
      * cloud_storage_uri: the cloud storage URI to sync gentoo distfiles to.
      * dryrun (bool): If True, run gsutil updates in a dryrun mode.
    """
    self._dryrun = dryrun
    self._rsync_mirror_address = rsync_mirror_address
    self._rsync_mirror_rate_limit = rsync_mirror_rate_limit
    self._cloud_storage_uri = cloud_storage_uri

  def run(self):

    # Use swarming cache from DupIit builders to persist gentoo_distfiles/
    # directory across builds (see the cache specification for DupIt builder
    # in
    # https://chrome-internal.googlesource.com/chromeos/infra/config/+/refs/heads/master/main.star)
    local_path = self.m.path['cache'].join('gentoo_distfiles')

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
        '--bwlimit=%s' % self.rsync_mirror_rate_limit
    ]
    rsync_commands += [self.rsync_mirror_address, local_path]
    self.m.step('Sync distfiles from %s' % self.rsync_mirror_address,
                rsync_commands)

    # NOTE: we must keep the old files/objects (i.e: not passing -d) since this
    # mirror is also used by old branches which rely on the old distfiles.
    gsutil_rsync_commands = ['rsync', '-r']  # recurse

    if self.dryrun:
      gsutil_rsync_commands.append('-n')

    gsutil_rsync_commands += [local_path, self.cloud_storage_uri]

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
  def rsync_mirror_rate_limit(self):
    return self._rsync_mirror_rate_limit

  @property
  def cloud_storage_uri(self):
    return self._cloud_storage_uri
