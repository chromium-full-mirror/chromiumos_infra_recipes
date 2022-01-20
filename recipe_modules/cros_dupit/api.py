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
                gs_distfiles_uri, ignore_missing_args=False,
                filter_missing_links=False):
    """Configure the DupIt script module.

    Args:
      * rsync_mirror_address: the rsync mirror address that contains Gentoo
        distfiles.
      * rsync_mirror_rate_limit: the rate limit of syncing from public mirror.
      * gs_distfiles_uri: the Google cloud storage URI which stores all
        Gentoo distfiles.
      * ignore_missing_args: have rsync ignore files that go missing during
        synchronization.
      * filter_missing_links: filter out symlinks that are missing (such
        as directories).
    """
    assert (rsync_mirror_address.endswith('distfiles') or
            rsync_mirror_address.endswith('distfiles/') or
            rsync_mirror_address.endswith('archlinux') or
            rsync_mirror_address.endswith('archlinux/'))
    self._rsync_mirror_address = rsync_mirror_address
    self._rsync_mirror_rate_limit = rsync_mirror_rate_limit
    self._gs_distfiles_uri = gs_distfiles_uri
    self._tmp_distfile_lists_path = self.m.path.mkdtemp('distfile_lists')
    self._tmp_distfiles_path = self.m.path.mkdtemp('distfiles')
    self._ignore_missing_args = ignore_missing_args
    self._filter_missing_links = filter_missing_links

  def _get_list_of_gs_distfiles(self):
    """Get relative, sorted list of distfile paths from Google Storage bucket"""

    # Get list of distfiles stored in gs, write to file.
    gs_distfile_list_path = self._tmp_distfile_lists_path.join('gs.txt')
    gsutil_ls_cmd = [
        'ls',
        '-r',
        self.m.path.join(self.gs_distfiles_uri, '**'),
    ]
    gsutil_ls_name = 'list distfiles in %s' % self.gs_distfiles_uri
    gsutil_ls_stdout = self.m.raw_io.output_text(leak_to=gs_distfile_list_path)
    self.m.gsutil(cmd=gsutil_ls_cmd, infra_step=True, name=gsutil_ls_name,
                  stdout=gsutil_ls_stdout)

    # Remove gs://... prefix (leaving relative path).
    # Before:
    #   gs://chromeos-mirror/gentoo/distfiles/path/to/distfile1.tar.gz
    #   gs://chromeos-mirror/gentoo/distfiles/path/to/distfile2.tar.gz
    #   ...
    # After:
    #   path/to/distfile1.tar.gz
    #   path/to/distfile2.tar.gz
    #   ...
    gs_distfile_relative_list_path = self._tmp_distfile_lists_path.join(
        'gs_relative.txt')
    cut_cmd = [
        'cut',
        '-c%d-' % (len(self.m.path.join(self.gs_distfiles_uri, '')) + 1),
        gs_distfile_list_path,
    ]
    cut_name = 'remove gs://... prefix'
    cut_stdout = self.m.raw_io.output_text(
        leak_to=gs_distfile_relative_list_path)
    self.m.step(cmd=cut_cmd, infra_step=True, name=cut_name, stdout=cut_stdout)

    # Ensure the list is sorted (for diffing).
    gs_distfile_relative_sorted_list_path = self._tmp_distfile_lists_path.join(
        'gs_relative_sorted.txt')
    sort_cmd = [
        'sort',
        gs_distfile_relative_list_path,
    ]
    sort_name = 'sort gs distfiles'
    sort_stdout = self.m.raw_io.output_text(
        leak_to=gs_distfile_relative_sorted_list_path)
    self.m.step(cmd=sort_cmd, infra_step=True, name=sort_name,
                stdout=sort_stdout)

    return gs_distfile_relative_sorted_list_path

  def _get_list_of_gentoo_distfiles(self):
    """Get relative, sorted list of distfile paths from Gentoo"""

    # Get list of gentoo distfiles, write to file.
    gentoo_distfile_list_path = self._tmp_distfile_lists_path.join('gentoo.txt')
    rsync_list_cmd = [
        'rsync',
        # List files.
        '--list-only',
        # Just to be safe.
        '--no-motd',
        # Recursively.
        '--recursive',
        # Symlinks are copied as symlinks.
        '--links',
        # Ignore symlinks that points to files outside of the root directory.
        '--safe-links',
        self.m.path.join(self.rsync_mirror_address, '**'),
    ]
    rsync_list_stdout = self.m.raw_io.output(leak_to=gentoo_distfile_list_path)
    rsync_list_name = 'list distfiles in %s' % self.rsync_mirror_address
    self.m.step(cmd=rsync_list_cmd, infra_step=True, name=rsync_list_name,
                stdout=rsync_list_stdout)

    # Remove perms/size/date prefix, and exclude dirs (i.e 00/, f2/, etc.).
    # Before:
    #   drwxr-xr-x 3,534,848 2019/12/19 08:54:29 f2
    #   lrwxrwxrwx        16 2019/12/15 13:53:37 foo.tar.gz -> f2/foo.tar.gz
    #   -rw-r--r-- 9,725,331 2018/02/25 01:22:12 bar.zip
    #   ...
    # After:
    #   foo.tar.gz
    #   bar.zip
    #   ...
    gentoo_distfile_relative_list_path = self._tmp_distfile_lists_path.join(
        'gentoo_relative.txt')
    awk_cmd = [
        'awk',
        'match($1, /^[^d]/) { print $5 }',
        gentoo_distfile_list_path,
    ]
    awk_name = 'remove perms/size/timestamp prefix'
    awk_stdout = self.m.raw_io.output(
        leak_to=gentoo_distfile_relative_list_path)
    self.m.step(cmd=awk_cmd, infra_step=True, name=awk_name, stdout=awk_stdout)

    # Sort the file for diffing.
    gentoo_distfile_relative_sorted_list_path = (
        self._tmp_distfile_lists_path.join('gentoo_relative_sorted.txt'))
    sort_cmd = [
        'sort',
        gentoo_distfile_relative_list_path,
    ]
    sort_name = 'sort gentoo distfiles'
    sort_stdout = self.m.raw_io.output_text(
        leak_to=gentoo_distfile_relative_sorted_list_path)
    self.m.step(cmd=sort_cmd, infra_step=True, name=sort_name,
                stdout=sort_stdout)

    return gentoo_distfile_relative_sorted_list_path

  def _get_rsync_cmd(self, files_from):
    cmd = [
        'rsync',
        # Make sure we copy files recursively.
        '--recursive',
        # Symlinks are copied as symlinks.
        '--links',
        # Ignore symlinks that points to files outside of the root directory.
        '--safe-links',
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
        # Ignore existing because we rsync again to get symlinked distfiles.
        '--ignore-existing',
        # IO timeout of 3 minutes.
        '--timeout=180',
        # Set rate-limit
        '--bwlimit=%s' % self.rsync_mirror_rate_limit,
        '--files-from=%s' % files_from,
    ]
    if self._ignore_missing_args:
      # Ignore files that vanish during large syncs.
      cmd.append('--ignore-missing-args')
    cmd.extend([
        # Ensure trailing slash on mirror address.
        self.m.path.join(self.rsync_mirror_address, ''),
        self.tmp_distfiles_path,
    ])
    return cmd

  def _rsync_new_distfiles_from_gentoo(self):
    """Rsync distfiles that are in Gentoo but not in GS to tmp dir"""

    # Determine distfiles in gentoo that are not in gs (new distfiles).
    gs_distfiles = self._get_list_of_gs_distfiles()
    gentoo_distfiles = self._get_list_of_gentoo_distfiles()
    new_distfiles = self._tmp_distfile_lists_path.join('new.txt')
    comm_cmd = [
        'comm',
        '-13',
        gs_distfiles,
        gentoo_distfiles,
    ]
    comm_name = 'get list of files in gentoo that are not in gs'
    comm_stdout = self.m.raw_io.output(leak_to=new_distfiles)
    self.m.step(cmd=comm_cmd, infra_step=True, name=comm_name,
                stdout=comm_stdout)

    # Rsync new gentoo distfiles to tmpdir.
    rsync_cmd = self._get_rsync_cmd(new_distfiles)
    rsync_name = 'rsync distfiles from %s' % self.rsync_mirror_address
    self.m.step(cmd=rsync_cmd, infra_step=True, name=rsync_name)

    # For symlinks, ensure we also rsync files they point to.
    # See https://crbug.com/1054836.
    symlinks = self.m.easy.stdout_step('list symlink distfiles', [
        'find',
        self.m.path.join(self.tmp_distfiles_path, ''),
        '-type',
        'l',
        '-ls',
    ]).strip()
    if symlinks:
      stdin = self.m.raw_io.input_text(symlinks)
      new_symlinked = self._tmp_distfile_lists_path.join('new_symlinked.txt')
      stdout = self.m.raw_io.output(leak_to=new_symlinked)
      cmd = [
          'awk',
          '{ print $NF }',
      ]
      self.m.step(cmd=cmd, infra_step=True,
                  name='get list of symlinked distfiles', stdin=stdin,
                  stdout=stdout)

      rsync_cmd = self._get_rsync_cmd(new_symlinked)
      rsync_name = ('ensure symlinked distfiles from %s' %
                    self.rsync_mirror_address)
      self.m.step(cmd=rsync_cmd, infra_step=True, name=rsync_name)

  def _copy_new_distfiles_to_gs(self):
    """Copy new distfiles from tmpdir to gs"""
    with self.m.step.nest('copy new distfiles to gs') as presentation:
      if self._filter_missing_links:
        # Remove any dangling symlinks.
        filter_cmd = [
            'find',
            self.m.path.join(self.tmp_distfiles_path, ''),
            '-xtype',
            'l',
            '-ls',
            '-delete',
        ]
        filter_name = 'filtering missing symlinks'
        self.m.step(cmd=filter_cmd, infra_step=True, name=filter_name)
      if self.m.file.listdir('list new distfiles', self.tmp_distfiles_path):
        gsutil_cp_cmd = [
            'cp',
            # Recursively copy the files.
            '-r',
            # No cloberring.
            '-n',
            # All distfiles are public-read.
            '-a',
            'public-read',
            self.m.path.join(self.tmp_distfiles_path, '*'),
            self.m.path.join(self.gs_distfiles_uri, ''),
        ]
        gsutil_cp_name = 'upload new distfiles to %s' % self.gs_distfiles_uri
        self.m.gsutil(cmd=gsutil_cp_cmd, multithreaded=True,
                      name=gsutil_cp_name, parallel_upload=True)
      else:
        presentation.step_text = 'No new distfiles to upload'

  def run(self):
    self._rsync_new_distfiles_from_gentoo()
    self._copy_new_distfiles_to_gs()

  @property
  def rsync_mirror_address(self):
    return self._rsync_mirror_address

  @property
  def rsync_mirror_rate_limit(self):
    return self._rsync_mirror_rate_limit

  @property
  def gs_distfiles_uri(self):
    return self._gs_distfiles_uri

  @property
  def tmp_distfiles_path(self):
    return self._tmp_distfiles_path
