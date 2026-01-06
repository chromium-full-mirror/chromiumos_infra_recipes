# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Dict, List, Optional

import re

from PB.chromite.api.dlc import GenerateDlcArtifactsListRequest
from PB.chromiumos import common as common_pb2
from PB.chromiumos.common import ArtifactsByService
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

# Number of seconds to wait on gsutil ops.

GSUTIL_TIMEOUT_SECONDS = 5 * 60
DEFAULT_DLC_DIRECTORIES = ['dlc']
DEFAULT_DLC_FILE_NAMES = ['dlc.img']
MATCH_EVERYTHING_AFTER_BUCKET = re.compile(r'gs://[^/]+/(.*)$')


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
        name='ls {}'.format(dlc_dir),
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
    with self.m.step.nest('Find DLCs'):
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

  def get_dlc_artifacts(self, gs_path: str) -> Dict[str, Dict[str, str]]:
    """Retrieves DLC artifact locations and corresponding file hashes.

    Args:
      gs_path: GS path used to report uploaded artifacts.

    Returns:
      Dict mapping DLC locations to file hashes.
    """
    with self.m.step.nest('Hash DLCs') as pres:
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
          dlc_artifacts[uploaded_dlc] = {'hash': file_hash}
        else:
          failed_logs.append(
              f'Failed to find corresponding local DLC (at {local_dlc}) for GS DLC (at {uploaded_dlc}).'
          )
          # Fall back to downloading the Google Storage version if we can't avoid the network call.
          self.m.gcloud.download_file(uploaded_dlc, local_dlc)
          file_hash = self.m.file.file_hash(local_dlc, test_data='deadbeef')
          dlc_artifacts[uploaded_dlc] = {'hash': file_hash}
      if failed_logs:
        failed_logs = [
            'The following DLCs were not found locally: '
        ] + failed_logs + ['Attempting to download from Google Storage.']
        pres.logs['failed local hashes'] = '\n'.join(failed_logs)
      return dlc_artifacts

  def copy_prebuilt_dlcs(
      self,
      bucket: str,
      sysroot: ArtifactsByService.Sysroot,
      chroot: common_pb2.Chroot,
      is_staging: bool,
  ) -> Dict[str, Dict[str, str]]:
    """Retrieves the list of prebuilt DLCs and copies them to the bucket.

    Args:
      bucket: GS bucket to copy into.
      sysroot: The sysroot to use.
      chroot: The chroot to use.
      is_staging: Whether this is running in the staging environment.

    Returns:
      Dict mapping DLC locations to file hashes.
    """
    with self.m.step.nest('upload prebuilt DLCs'):
      resp = None
      # Quick branch check.
      if self.m.cros_build_api.has_endpoint(self.m.cros_build_api.DlcService,
                                            'GenerateDlcArtifactsList'):
        # Retrieve the list of DLCs from the Build API.
        resp = self.m.cros_build_api.DlcService.GenerateDlcArtifactsList(
            GenerateDlcArtifactsListRequest(sysroot=sysroot, chroot=chroot))
      ret = {}
      if not resp or not resp.dlc_artifacts:
        return ret

      runner = self.m.future_utils.create_parallel_runner()

      for artifact in resp.dlc_artifacts:
        # Parse out the location to copy to from the path.
        path = artifact.gs_uri_path
        parsed_path = MATCH_EVERYTHING_AFTER_BUCKET.match(path).group(1)
        # Copy all the DLCs from the locations given to the bucket.
        env_string = 'staging' if is_staging else 'prod'
        new_location = f'gs://{bucket}/{env_string}-dlc-images/{parsed_path}'
        if self.m.gcloud.storage_ls(new_location).retcode != 0:
          runner.run_function_async(
              lambda paths, _: self.m.gcloud.storage_cp(
                  paths[0], paths[1], flags=['--recursive', '--no-clobber']),
              [path, new_location])
        # Construct the object for each one.
        key = f'{new_location}/{artifact.image_name}'
        if key in ret and ret[key] != artifact.image_hash:
          raise StepFailure('Duplicate DLCs with different hashes provided')
        ret[key] = {
            'hash': artifact.image_hash,
            'id': artifact.id,
        }

      runner.wait_for_and_throw()

      return ret

  def infer_dlc_name(self, path: str) -> str:
    """Infers the DLC name from a path by looking for the first path component after `self._dlc_directories`."""
    parts = path.split(self.m.path.sep)

    for i, part in enumerate(parts):
      if part in self._dlc_directories:
        if i + 1 < len(parts):
          return parts[i + 1]

    return path.lstrip('/').replace('/', '-')
