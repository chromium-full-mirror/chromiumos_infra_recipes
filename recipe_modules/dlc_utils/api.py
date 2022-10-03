# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

# Number of seconds to wait on gsutil ops.

GSUTIL_TIMEOUT_SECONDS = 5 * 60
DEFAULT_DLC_DIRECTORIES = ['dlc']
DEFAULT_DLC_FILE_NAMES = ['dlc.img']


class DlcUtilsApi(recipe_api.RecipeApi):
  """A module handle special operations around DLCs."""

  def __init__(self, properties, *args, **kwargs):
    super(DlcUtilsApi, self).__init__(*args, **kwargs)
    self._dlc_directories = properties.dlc_directories or DEFAULT_DLC_DIRECTORIES
    self._dlc_file_names = properties.dlc_file_names or DEFAULT_DLC_FILE_NAMES

  def get_dlcs_in_path(self, gs_image_dir):
    """Retrieves a list of DLCs in the provided path.

    Args:
      gs_image_dir: the GS location to search inside.

    Returns:
      List[str] of fully qualified GS paths of DLCs within the path.
    """
    dlcs = []
    # Loop through each directory.
    for dlc_dir in self._dlc_directories:
      recursive_uri = self.m.path.join(gs_image_dir, dlc_dir, '**')
      gsutil_ls_stdout = self.m.raw_io.output_text(name='gsutil ls results',
                                                   add_output_log=True)
      listing = self.m.gsutil.list(
          recursive_uri,
          name="ls {}".format(dlc_dir),
          timeout=GSUTIL_TIMEOUT_SECONDS,
          stdout=gsutil_ls_stdout,
          # Be ok with empty/missing directories.
          ok_ret=(0, 1))

      for uri in listing.stdout.split():
        for filename in self._dlc_file_names:
          if uri.endswith(filename):
            dlcs.append(uri)

    return dlcs
