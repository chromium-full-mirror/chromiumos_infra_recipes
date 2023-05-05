# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Dict, List, Optional

from recipe_engine import recipe_api

# Number of seconds to wait on gsutil ops.

GSUTIL_TIMEOUT_SECONDS = 5 * 60
DEFAULT_DLC_DIRECTORIES = ['dlc']
DEFAULT_DLC_FILE_NAMES = ['dlc.img']


class DlcUtilsApi(recipe_api.RecipeApi):
  """A module handle special operations around DLCs."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._dlc_directories = properties.dlc_directories or DEFAULT_DLC_DIRECTORIES
    self._dlc_file_names = properties.dlc_file_names or DEFAULT_DLC_FILE_NAMES
    self._artifacts_local_path = None

  @property
  def artifacts_local_path(self) -> str:
    """Return the local path where artifacts are placed by BAPI, if set."""
    return self._artifacts_local_path

  @artifacts_local_path.setter
  def artifacts_local_path(self, artifacts_local_path: str):
    """Set the local path where artifacts are placed by BAPI."""
    self._artifacts_local_path = artifacts_local_path

  def _get_gs_recursive_uri(self, gs_image_dir: str, dlc_dir: str) -> str:
    """Returns GS path to use for listing DLCs."""
    return self.m.path.join(gs_image_dir, dlc_dir, '**')

  def _get_local_path(self, local_artifact_path: str, dlc_dir: str) -> str:
    """Returns local path to use for listing DLCs."""
    return self.m.path.join(local_artifact_path, dlc_dir)

  def _list_gs_dlcs(self, recursive_uri: str, dlc_dir: str) -> List[str]:
    """Returns list of DLCs from provided GS path."""
    gsutil_ls_stdout = self.m.raw_io.output_text(name='gsutil ls results',
                                                 add_output_log=True)
    listing = self.m.gsutil.list(
        recursive_uri,
        name="ls {}".format(dlc_dir),
        timeout=GSUTIL_TIMEOUT_SECONDS,
        stdout=gsutil_ls_stdout,
        # Be ok with empty/missing directories.
        ok_ret=(0, 1))
    return listing.stdout.split()

  def _list_local_dlcs(self, full_dlc_dir: str) -> List[str]:
    """Returns list of DLCs from provided local path."""
    full_dlc_dir = self.m.path.abs_to_path(full_dlc_dir)
    listed_files = self.m.file.listdir('list local DLCs', full_dlc_dir,
                                       recursive=True)
    return [str(file) for file in listed_files]

  def get_dlcs_in_path(self, path: str,
                       use_local_path: Optional[bool] = False) -> List[str]:
    """Retrieves a list of DLCs in the provided local or GS path.

    Args:
      path: Location to search for DLCs.
      use_local_path: Whether the path is local (vs. GS).

    Returns:
      List of fully qualified paths of DLCs within the path.
    """
    with self.m.step.nest("Find DLCs"):
      dlc_paths = []
      # Loop through each directory.
      for dlc_dir in self._dlc_directories:
        if use_local_path:
          list_path = self._get_local_path(path, dlc_dir)
          listed_files = self._list_local_dlcs(list_path)
        else:
          list_path = self._get_gs_recursive_uri(path, dlc_dir)
          listed_files = self._list_gs_dlcs(list_path, dlc_dir)

        # Only return files that are DLCs.
        for uri in listed_files:
          for filename in self._dlc_file_names:
            if uri.endswith(filename):
              dlc_paths.append(uri)

      return dlc_paths

  def get_dlc_artifacts(self, gs_path: str) -> Dict[str, str]:
    """Retrieves DLC artifact locations and corresponding file hashes.

    Args:
      gs_path: GS path used to report uploaded artifacts.

    Returns:
      Dict mapping DLC locations to file hashes.
    """
    with self.m.step.nest("Hash DLCs") as pres:
      dlc_artifacts = {}
      failed_logs = []
      # List uploaded DLCs
      uploaded_dlcs = self.get_dlcs_in_path(gs_path)
      for uploaded_dlc in uploaded_dlcs:
        # Look for a local version to hash.
        local_dlc = uploaded_dlc.replace(gs_path, self.artifacts_local_path)
        # Double check the local version exists.
        if self.m.path.exists(local_dlc):
          file_hash = self.m.file.file_hash(local_dlc, test_data='deadbeef')
          # Report the uploaded location.
          dlc_artifacts[uploaded_dlc] = file_hash
        else:
          failed_logs.append(
              f'Failed to find corresponding local DLC (at {local_dlc}) for GS DLC (at {uploaded_dlc}).'
          )
          # Fall back to downloading the Google Storage version if we can't avoid the network call.
          self.m.gcloud.download_file(uploaded_dlc, local_dlc)
          file_hash = self.m.file.file_hash(local_dlc, test_data='deadbeef')
          dlc_artifacts[uploaded_dlc] = file_hash
      if failed_logs:
        failed_logs = [
            'The following DLCs were not found locally: '
        ] + failed_logs + ['Attempting to download from Google Storage.']
        pres.logs['failed local hashes'] = "\n".join(failed_logs)
      return dlc_artifacts
