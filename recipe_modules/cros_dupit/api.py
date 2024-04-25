# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for DupIt script. See the design of this recipe in go/cros-dupit."""

from recipe_engine import recipe_api


class DupItApi(recipe_api.RecipeApi):
  """A module for the DupIt script."""

  def configure(self, rsync_mirror_address, rsync_mirror_rate_limit,
                gs_distfiles_uri, ignore_missing_args=False,
                filter_missing_links=False, regex_for_archival_sync=None,
                gs_uri_for_archival_sync=None,
                path_datetime_for_archival_sync=None, gs_topdir_backfill=False):
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
      * regex_for_archival_sync: if this string is non-empty,
        sync any files from the remote mirror that match the regex.
      * gs_uri_for_archival_sync: the base GS URI used for syncing
        files matching 'regex_for_archival_sync'.
      * path_datetime_for_archival_sync: an additional path for archival
        syncing that is interpreted by datetime strftime (using UTC). Gets
        added to the end of 'gs_uri_for_archival_sync'.
      * gs_topdir_backfill: enable a workaround for Gentoo distfiles. See
        b/302226413 for more information.
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
    self._additional_regex_matches_file = self._tmp_distfile_lists_path.joinpath(
        'additional_regex_matches_file.txt')
    self._ignore_missing_args = ignore_missing_args
    self._filter_missing_links = filter_missing_links
    self._regex_for_archival_sync = regex_for_archival_sync
    self._gs_uri_for_archival_sync = gs_uri_for_archival_sync
    self._path_datetime_for_archival_sync = path_datetime_for_archival_sync
    self._gs_topdir_backfill = gs_topdir_backfill

  def _get_list_of_gs_distfiles(self):
    """Get relative, sorted list of distfile paths from Google Storage bucket"""

    # Get list of distfiles stored in gs, write to file.
    gs_distfile_list_path = self._tmp_distfile_lists_path / 'gs.txt'
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
    gs_distfile_relative_list_path = self._tmp_distfile_lists_path.joinpath(
        'gs_relative.txt')
    cut_cmd = [
        'cut',
        '-c%d-' % (len(self.m.path.join(self.gs_distfiles_uri, '')) + 1),
        gs_distfile_list_path,
    ]
    cut_name = 'remove gs://... prefix'
    cut_stdout = self.m.raw_io.output_text(
        leak_to=gs_distfile_relative_list_path,
        name=self.m.path.basename(gs_distfile_relative_list_path))
    self.m.step(cmd=cut_cmd, name=cut_name, stdout=cut_stdout)

    # Ensure the list is sorted (for diffing).
    gs_distfile_relative_sorted_list_path = self._tmp_distfile_lists_path.joinpath(
        'gs_relative_sorted.txt')
    sort_cmd = [
        'sort',
        gs_distfile_relative_list_path,
    ]
    sort_name = 'sort gs distfiles'
    sort_stdout = self.m.raw_io.output_text(
        leak_to=gs_distfile_relative_sorted_list_path,
        name=self.m.path.basename(gs_distfile_relative_sorted_list_path),
        add_output_log=True)
    self.m.step(cmd=sort_cmd, name=sort_name, stdout=sort_stdout)

    return gs_distfile_relative_sorted_list_path

  def _get_list_of_gentoo_distfiles(self):
    """Get relative, sorted list of distfile paths from Gentoo"""

    # Get list of gentoo distfiles, write to file.
    gentoo_distfile_list_path = self._tmp_distfile_lists_path / 'gentoo.txt'
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
        # Add a timeout of 6 hours.
        '--timeout=%d' % (6 * 60 * 60),
        self.m.path.join(self.rsync_mirror_address, '**'),
    ]
    rsync_list_stdout = self.m.raw_io.output(
        leak_to=gentoo_distfile_list_path,
        name=self.m.path.basename(gentoo_distfile_list_path),
        add_output_log=True)
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
    gentoo_distfile_relative_list_path = self._tmp_distfile_lists_path.joinpath(
        'gentoo_relative.txt')
    awk_cmd = [
        'awk',
        'match($1, /^[^d]/) { print $5 }',
        gentoo_distfile_list_path,
    ]
    awk_name = 'remove perms/size/timestamp prefix'
    awk_stdout = self.m.raw_io.output(
        leak_to=gentoo_distfile_relative_list_path,
        name=self.m.path.basename(gentoo_distfile_relative_list_path),
        add_output_log=True)
    self.m.step(cmd=awk_cmd, name=awk_name, stdout=awk_stdout)

    # Sort the file for diffing.
    gentoo_distfile_relative_sorted_list_path = (
        self._tmp_distfile_lists_path / 'gentoo_relative_sorted.txt')
    sort_cmd = [
        'sort',
        gentoo_distfile_relative_list_path,
    ]
    sort_name = 'sort gentoo distfiles'
    sort_stdout = self.m.raw_io.output_text(
        leak_to=gentoo_distfile_relative_sorted_list_path,
        name=self.m.path.basename(gentoo_distfile_relative_sorted_list_path),
        add_output_log=True)
    self.m.step(cmd=sort_cmd, name=sort_name, stdout=sort_stdout)

    return gentoo_distfile_relative_sorted_list_path

  def _backfill_gs_topdir(self, distfiles):
    """Populate the topdir of the gs bucket.

    Gentoo has migrated to GLEP-0075 which only creates subdirs now of files
    rather than duplicating them in the topdir.  Since our builders still look
    for files in the topdir, we need to backfill.  http://b/302226413

    Args:
      * distfiles: List of files in the bucket.
    """
    # The distfiles text file will contain a relative list of files in the GS
    # bucket like:
    #   foo.tar.gz
    #   ad/1.tar.gz

    with self.m.step.nest('backfill gs distfiles topdir'):
      # Extract the set of files that exist in the distfiles/ topdir now.  e.g.
      #   foo.tar.gz
      topfiles_txt = self._tmp_distfile_lists_path / 'gs_topfiles.txt'
      topfiles_cmd = [
          'grep',
          '-v',
          '/',
          distfiles,
      ]
      topfiles_name = 'get list of files in topdir'
      topfiles_stdout = self.m.raw_io.output(
          leak_to=topfiles_txt, name=self.m.path.basename(topfiles_txt),
          add_output_log=True)
      self.m.step(cmd=topfiles_cmd, name=topfiles_name, stdout=topfiles_stdout)

      # Extract the set of files that exist in GLEP-0075 subdirs.  Ignore the
      # rest as we only care about the Gentoo mirror behavior.  e.g.
      #   ad/1.tar.gz
      subfiles_txt = self._tmp_distfile_lists_path / 'gs_subfiles.txt'
      subfiles_cmd = [
          'grep',
          '-E',
          '^[0-9a-f]{2}/[^/]+$',
          distfiles,
      ]
      subfiles_name = 'get list of files in hashed subdirs'
      subfiles_stdout = self.m.raw_io.output(
          leak_to=subfiles_txt, name=self.m.path.basename(subfiles_txt),
          add_output_log=True)
      self.m.step(cmd=subfiles_cmd, name=subfiles_name, stdout=subfiles_stdout)

      # Read the text files into memory so we can do some fast set operations.
      topfiles = self.m.file.read_text('read list of topfiles', topfiles_txt,
                                       test_data='1.tar\n')
      subfiles = self.m.file.read_text('read list of subfiles', subfiles_txt,
                                       test_data='12/2.tar\naa/1.tar\n')

      # Find all the files that exist only in the GLEP-0075 subdirs.  i.e.,
      # all the files that are missing from the distfiles/ topdir.
      topfiles = set(topfiles.splitlines())
      subfiles = subfiles.splitlines()

      missing_subfiles = [
          x for x in subfiles if x.split('/')[-1] not in topfiles
      ]
      srcuris = [
          f'{self.gs_distfiles_uri.rstrip("/")}/{x}' for x in missing_subfiles
      ]
      if srcuris:
        # If we found files that only exist in subdirs, copy them to the topdir.
        # e.g. gsutil cp gs://.../distfiles/ad/1.tar.gz gs://.../distfiles/
        self.m.gsutil(
            cmd=[
                'cp',
                '-n',
                # All distfiles are public-read.
                '-a',
                'public-read'
            ] + srcuris + [self.gs_distfiles_uri],
            name='syncing subfiles to topdir')

  def _populate_list_of_additional_regex_matches(self, distfiles):
    """Populate relative list of all files matching the additional regex.

    Extracts the list of files matching the regex supplied by
    'regex_for_archival_sync' expression and stores it in
    the tempfile 'self._additional_regex_matches_file'.

    Args:
      * distfiles: Path to a newline separated list of distfiles.
    """
    grep_cmd = [
        'egrep',
        # Show only lines matching the properties-provided regex
        self._regex_for_archival_sync,
        distfiles,
    ]
    grep_name = 'get list of files matching additional regex'
    grep_stdout = self.m.raw_io.output_text(
        leak_to=self._additional_regex_matches_file, name='regex_grep',
        add_output_log=True)
    self.m.step(cmd=grep_cmd, name=grep_name, stdout=grep_stdout)

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

  def _add_regex_files_to_distfile_list(self, distfiles):
    """Combine additional regex files with new distfiles.

    Concatenates the additional regex filelist with the new distfiles list and
    returns the path to a sorted and unique list.

    Args:
      * distfiles: Path to a newline separated list of distfiles.

    Returns:
      A string representing the path to a tempfile. The file is in the same
      format as the 'distfiles' argument.
    """
    # Join and sort distfiles with regex filelist.
    distfiles_regex_sorted = self._tmp_distfile_lists_path.joinpath(
        'new_regex_sorted.txt')
    sortuniq_cmd = [
        'sort',
        '--unique',
        self._additional_regex_matches_file,
        distfiles,
    ]
    sortuniq_name = 'add additional regex files to distfiles list'
    sortuniq_stdout = self.m.raw_io.output(
        leak_to=distfiles_regex_sorted,
        name=self.m.path.basename(distfiles_regex_sorted), add_output_log=True)
    self.m.step(cmd=sortuniq_cmd, name=sortuniq_name, stdout=sortuniq_stdout)

    return distfiles_regex_sorted

  def _rsync_new_distfiles_from_gentoo(self):
    """Rsync distfiles that are in Gentoo but not in GS to tmp dir"""

    # Determine distfiles in gentoo that are not in gs (new distfiles).
    gs_distfiles = self._get_list_of_gs_distfiles()
    gentoo_distfiles = self._get_list_of_gentoo_distfiles()
    new_distfiles = self._tmp_distfile_lists_path / 'new.txt'
    comm_cmd = [
        'comm',
        '-13',
        gs_distfiles,
        gentoo_distfiles,
    ]
    comm_name = 'get list of files in gentoo that are not in gs'
    comm_stdout = self.m.raw_io.output(leak_to=new_distfiles,
                                       name=self.m.path.basename(new_distfiles),
                                       add_output_log=True)
    self.m.step(cmd=comm_cmd, name=comm_name, stdout=comm_stdout)

    if self._gs_topdir_backfill:
      self._backfill_gs_topdir(gs_distfiles)

    if self._regex_for_archival_sync:
      # Populate our list of regex matches
      self._populate_list_of_additional_regex_matches(gentoo_distfiles)
      # Add additional regex files to the list of distfiles to be rsync'd
      new_distfiles = self._add_regex_files_to_distfile_list(new_distfiles)

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
      new_symlinked = self._tmp_distfile_lists_path / 'new_symlinked.txt'
      stdout = self.m.raw_io.output(leak_to=new_symlinked,
                                    name=self.m.path.basename(new_symlinked),
                                    add_output_log=True)
      cmd = [
          'awk',
          '{ print $NF }',
      ]
      self.m.step(cmd=cmd, name='get list of symlinked distfiles', stdin=stdin,
                  stdout=stdout)

      # (b/273524588) Remove leading `../` from paths. As of rsync 3.1.2 this
      # is no longer allowed since the files being received aren't the same as
      # those in the --files-from list.
      fixed_symlinked = self._tmp_distfile_lists_path.joinpath(
          'fixed_symlinked.txt')
      stdout = self.m.raw_io.output(leak_to=fixed_symlinked,
                                    name=self.m.path.basename(fixed_symlinked),
                                    add_output_log=True)
      cmd = ['sed', '-e', r's#^\(\.\./\)*##g', new_symlinked]
      self.m.step(cmd=cmd, name='make distfiles paths absolute', stdout=stdout)

      rsync_cmd = self._get_rsync_cmd(fixed_symlinked)
      rsync_name = ('ensure symlinked distfiles from %s' %
                    self.rsync_mirror_address)
      self.m.step(cmd=rsync_cmd, infra_step=True, name=rsync_name)

  def _write_empty_file_to_gs(self, gs_path, step_name):
    """Creates an empty temp file and then copies to gs_path.

    Args:
      * gs_path: Google Cloud Storage URI to upload the empty file to. Filename
        should be included in this.
      * step_name: name of the gsutil upload step to be shown in LUCI.
    """
    tempfile = self.m.path.mkstemp()
    self.m.gsutil(cmd=['cp', tempfile, gs_path], name=step_name)

  def _write_string_to_gs_file(self, gs_path, contents, step_name):
    """Creates a text file with 'contents' and then copies to gs_path.

    Args:
      * gs_path: Google Cloud Storage URI to upload the empty file to. Filename
        should be included in this.
      * contents: a string to be written to the body of the file.
      * step_name: name of the gsutil upload step to be shown in LUCI.
    """
    tempfile = self.m.path.mkstemp()
    self.m.file.write_text('write string contents to tempfile', tempfile,
                           contents)
    self.m.gsutil(cmd=['cp', tempfile, gs_path], name=step_name)

  def _archive_distfiles_to_gs(self, gs_uri, path_datetime, distfiles,
                               files_description='distfiles',
                               donefile_name='.done'):
    """Upload an additional copy of distfiles for archival.

    Upload the files in the directory 'distfiles' points to to a Google Cloud
    Storage URI for archival.

    After the upload is complete create an empty file called 'done' at the
    provided Google Cloud Storage URI. This step is to work around Google
    Storage not supporting atomic moves so any consumer of this function can
    ensure the upload was completed successfully.

    Args:
      * gs_uri: Google Cloud Storage URI to upload to (path_datetime is
        appeneded to this URL)
      * path_datetime: path to append to gs_uri. This is interpreted by
        datetime's strftime before appending.
      * distfiles: Path to the distfiles to be archived.
      * files_description: used in the step name to allow the step to be more
        descriptive (default='distfiles').
      * donefile_name: name to be given to the empty file created after archive
        upload is completed (default='.done').
    """
    # Interpret timecodes in the archive URI.
    time_now_utc = self.m.time.utcnow()
    date_path = time_now_utc.strftime(path_datetime)
    gs_uri_dated = self.m.path.join(gs_uri, date_path)

    gsutil_cp_cmd = [
        'cp',
        # Recursively copy the files.
        '-r',
        # No cloberring.
        '-n',
        # All distfiles are public-read.
        '-a',
        'public-read',
        self.m.path.join(distfiles, '*'),
        self.m.path.join(gs_uri_dated, ''),
    ]
    gsutil_cp_name = 'archive %s to %s' % (files_description, gs_uri_dated)
    self.m.gsutil(cmd=gsutil_cp_cmd, multithreaded=True, name=gsutil_cp_name,
                  parallel_upload=True)

    # Create the donefile to signify we successfully uploaded.
    donefile_gs_uri = self.m.path.join(gs_uri_dated, donefile_name)
    donefile_step_name = 'create donefile at %s' % donefile_gs_uri
    self._write_empty_file_to_gs(gs_path=donefile_gs_uri,
                                 step_name=donefile_step_name)

    # Write the latest sync file to gs://gs_uri/latest_sync
    latestsync_gs_uri = self.m.path.join(gs_uri, 'latest_sync')
    latestsync_step_name = 'create latest_sync at %s' % latestsync_gs_uri
    self._write_string_to_gs_file(latestsync_gs_uri, date_path,
                                  latestsync_step_name)

  def _sync_additional_regex_matches_to_gs(self):
    """Copy files matching the additional regex from tmpdir to gs"""
    tmp_regexfiles_path = self.m.path.mkdtemp('regexfiles')
    # Use rsync to create a copy of our mirror with just the
    # files we want to force upload to Google cloud storage.
    rsync_regex_cmd = [
        'rsync',
        # Avoid creating empty directory structures.
        '--prune-empty-dirs',
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
        '--files-from=%s' % self._additional_regex_matches_file,
        self.tmp_distfiles_path,
        tmp_regexfiles_path,
    ]
    rsync_regex_name = 'prepare additional regex files for sync'
    self.m.step(cmd=rsync_regex_cmd, infra_step=True, name=rsync_regex_name)

    # Copy the files with clobbering to force update regex files.
    gsutil_cp_cmd = [
        'cp',
        # Recursively copy the files.
        '-r',
        # All distfiles are public-read.
        '-a',
        'public-read',
        self.m.path.join(tmp_regexfiles_path, '*'),
        self.m.path.join(self.gs_distfiles_uri, ''),
    ]
    gsutil_cp_name = 'upload additional regex files to %s' % self.gs_distfiles_uri
    self.m.gsutil(cmd=gsutil_cp_cmd, multithreaded=True, name=gsutil_cp_name,
                  parallel_upload=True)

    if self._gs_uri_for_archival_sync:
      self._archive_distfiles_to_gs(self._gs_uri_for_archival_sync,
                                    self._path_datetime_for_archival_sync,
                                    tmp_regexfiles_path,
                                    files_description='additional regex files',
                                    donefile_name='.dupit_done')

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
        self.m.step(cmd=filter_cmd, name=filter_name)
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

        if self._regex_for_archival_sync:
          self._sync_additional_regex_matches_to_gs()
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
