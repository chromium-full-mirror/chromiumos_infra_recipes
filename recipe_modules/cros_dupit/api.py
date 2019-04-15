# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for DupIt script. See the design of this recipe in go/cros-dupit."""

from recipe_engine import recipe_api


class DupItApi(recipe_api.RecipeApi):
  """A module for the DupIt script."""

  def __init__(self, *args, **kwargs):
    super(DupItApi, self).__init__(*args, **kwargs)

  def configure(self, rsync_mirror_address, rsync_mirror_rate_limit,
                latest_gs_distfiles_uri, all_gs_distfiles_uri):
    """Configure the DupIt script module.

    Args:
      * rsync_mirror_address: the rsync mirror address that contains Gentoo
        distfiles
      * rsync_mirror_rate_limit: the rate limit of syncing from public mirror.
      * latest_gs_distfiles_uri: the Google cloud storage URI which's supposed
          to store the latest Gentoo distfiles. The content of this should be
          very similar to that of a public Gentoo mirror.
      * all_gs_distfiles_uri: the Google cloud storage URI which's supposed
          to store the all Gentoo distfiles.
    """
    assert (rsync_mirror_address.endswith('distfiles') or
            rsync_mirror_address.endswith('distfiles/'))
    self._rsync_mirror_address = rsync_mirror_address
    self._rsync_mirror_rate_limit = rsync_mirror_rate_limit
    self._latest_gs_distfiles_uri = latest_gs_distfiles_uri
    self._all_gs_distfiles_uri = all_gs_distfiles_uri
    # Use swarming cache from DupIit builders to persist gentoo_distfiles/
    # directory across builds (see the cache specification for DupIt builder
    # in
    # https://chrome-internal.googlesource.com/chromeos/infra/config/+/refs/heads/master/main.star)
    self._local_distfiles_cache = self.m.path['cache'].join('gentoo_distfiles')

  def _rsync_from_latest_gs_distfiles(self):
    # Recursively sync all files from latest_gs_distfiles_uri.
    gsutil_rsync_commands = [
        'rsync', '-r', self.latest_gs_distfiles_uri, self.local_distfiles_cache
    ]

    self.m.gsutil(
        cmd=gsutil_rsync_commands,
        name='Download distfiles from %s' % self.latest_gs_distfiles_uri,
        parallel_upload=True, multithreaded=True)

  def _rsync_from_public_gentoo_distfiles(self):
    rsync_commands = [
        'rsync',
        # Make sure we copy files recursively.
        '--recursive',
        # Symlinks are copied as symlinks.
        '--links',
        # Ignore symlinks that points to files outside of the root directory.
        '--safe-links',
        # Delete extra files to ensure the local directory's content closely
        # match that of the public mirror.
        '--delete',
        # Preserve files permission.
        '--perms',
        # Preserve modification times.
        '--times',
        # Compress files during transfer to save bandwidth.
        '--compress',
        # Log out file-transfer stats for debugging.
        '--stats',
        # Shows progress during transfer.
        '--progress',
        '--human-readable',
        # IO timeout of 3 minutes.
        '--timeout=180',
        '--bwlimit=%s' % self.rsync_mirror_rate_limit
    ]
    rsync_commands += [self.rsync_mirror_address, self.local_distfiles_cache]
    self.m.step('Sync distfiles from %s' % self.rsync_mirror_address,
                rsync_commands)

  def _rsync_to_latest_gs_distfiles(self):
    # Recursively sync all files to latest_gs_distfiles_uri & remove stale
    # files/objects in the bucket.
    gsutil_rsync_commands = [
        'rsync', '-r', '-d', self.local_distfiles_cache,
        self.latest_gs_distfiles_uri
    ]

    self.m.gsutil(
        cmd=gsutil_rsync_commands,
        name='Sync latest distfiles to %s' % self.latest_gs_distfiles_uri,
        parallel_upload=True, multithreaded=True)

  def _copy_new_files_to_all_gs_distfiles(self):
    # NOTE: there have been more than one scenario where a file was updated by
    # upstream (beyond Gentoo) and the contents were otherwise unchanged.
    # In either cases, we must keep the old files/objects in the
    # all_gs_distfiles bucket unchanged to avoid breaking builds.
    #
    # For the scenarios where we want the newer/fixed archive, developers can
    # do the rename & upload to all_gs_distfiles_uri manually to workaround the
    # bad behavior of the upstream project.
    gsutil_cp_commands = [
        'cp',
        # Recursively copy the files.
        '-r',
        # No cloberring.
        '-n',
        # Preserve files ACLs.
        '-p'
    ]

    gsutil_cp_commands += [
        self.m.path.join(self.local_distfiles_cache, 'distfiles', '*'),
        self.all_gs_distfiles_uri
    ]

    self.m.gsutil(cmd=gsutil_cp_commands,
                  name='Upload new distfiles to %s' % self.all_gs_distfiles_uri,
                  parallel_upload=True, multithreaded=True)

  def run(self):
    self._rsync_from_latest_gs_distfiles()
    self._rsync_from_public_gentoo_distfiles()
    self._copy_new_files_to_all_gs_distfiles()
    self._rsync_to_latest_gs_distfiles()

  @property
  def rsync_mirror_address(self):
    return self._rsync_mirror_address

  @property
  def rsync_mirror_rate_limit(self):
    return self._rsync_mirror_rate_limit

  @property
  def latest_gs_distfiles_uri(self):
    return self._latest_gs_distfiles_uri

  @property
  def all_gs_distfiles_uri(self):
    return self._all_gs_distfiles_uri

  @property
  def local_distfiles_cache(self):
    return self._local_distfiles_cache
