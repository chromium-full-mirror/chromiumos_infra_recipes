# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS prebuilts to Google Storage."""

import os

from recipe_engine import recipe_api

from PB.chromite.api import binhost
from PB.chromiumos import builder_config


class CrosPrebuiltsApi(recipe_api.RecipeApi):
  """A module for uploading package prebuilts."""

  def __init__(self, prebuilts_use_staging_branch, **kwargs):
    super(CrosPrebuiltsApi, self).__init__(**kwargs)
    self._use_staging_branch = prebuilts_use_staging_branch

  def _prebuilts_uri(self, target, kind, gs_bucket):
    """Determine the GS URI to upload prebuilts.

    Args:
      target (BuildTarget): The build target.
      kind (BuilderConfig.Id.Type): The kind of prebuilts, e.g. POSTSUBMIT
      gs_bucket (str): Google storage bucket to upload prebuilts to.

    Returns:
      The full GS URI in which to upload prebuilts.
    """
    label = builder_config.BuilderConfig.Id.Type.Name(kind).lower()
    version = self.m.cros_version.read_workspace_version()
    return 'gs://%s/board/%s/%s-%s/packages' % (gs_bucket, target.name, label,
                                                version)

  def _binhost_key(self, kind):
    """Return the binhost key for the given builder type.

    Args:
      kind (BuilderConfig.Id.Type): The builder type.

    Returns:
      BinhostKey: The binhost key.

    Raises:
      ValueError: If prebuilts are not supported for the given builder type.
    """
    name = builder_config.BuilderConfig.Id.Type.Name(kind)
    try:
      return binhost.BinhostKey.Value('%s_BINHOST' % name.upper())
    except ValueError as err:
      err.message = '%s builders may not upload prebuilts' % name.lower()
      raise

  def _prepare_binhost_uploads(self, target, uri):
    """Determine which prebuilt archives should be uploaded to the binhost.

    Args:
      target (BuildTarget): Build target whose prebuilts will be uploaded.
      uri (str): URI where prebuilts will be uploaded.

    Returns:
      tuple(Path, List[str]): Path to directory containing uploads and
          a list of uploadable string paths relative to that directory.
    """
    with self.m.step.nest('prepare binhost uploads'):
      response = self.m.cros_build_api.BinhostService.PrepareBinhostUploads(
          binhost.PrepareBinhostUploadsRequest(build_target=target, uri=uri),
          infra_step=True)
      upload_root = self.m.path.abs_to_path(response.uploads_dir)
      upload_paths = [ut.path for ut in response.upload_targets]
      return upload_root, upload_paths

  def _set_binhost(self, target, private, key, uri):
    """Set the target's Portage binhost to point to the given URI.

    This function updates a conf file within the target's overlay, commits the
    change, and pushes it.

    Args:
      target (BuildTarget): Build target to update the binhost for.
      private (bool): Whether the target's binhost is private.
      key (BinhostKey): The binhost key, e.g. POSTSUBMIT_BINHOST.
      uri (str): The new binhost URI.
    """
    with self.m.step.nest('update binhost conf file'):
      request = binhost.SetBinhostRequest(build_target=target, private=private,
                                          key=key, uri=uri)
      response = self.m.cros_build_api.BinhostService.SetBinhost(
          request, infra_step=True)
      binhost_path = self.m.path.abs_to_path(response.output_file)
      binhost_data = self.m.file.read_text('read binhost conf', binhost_path)

      projects = self.m.repo.project_infos(projects=[binhost_path])
      assert len(projects) == 1, '%s must belong to 1 project' % binhost_path
      project = projects[0]

      # Staging doesn't have ACLs to push conf files to the real branch.
      # Instead, use a branch with the last component named 'staging'
      branch = project.branch

      if self._use_staging_branch:
        branch_parts = branch.split('/')
        branch_parts[-1] = 'staging'
        branch = '/'.join(branch_parts)

      with self.m.context(
          cwd=self.m.cros_source.workspace_path.join(project.path)):
        self.m.git_txn.update_ref_write_file(
            project.remote, branch,
            'Set %s=%s.' % (binhost.BinhostKey.Name(key), uri), binhost_path,
            binhost_data, automerge=True)

  def _upload(self, root, paths, uri):
    """Upload the paths within root to the GS URI.

    This function symlinks all paths within the root directory to a temporary
    directory and then runs `gsutil rsync` to upload them. We use rsync because
    the uploads run in parallel and because it dedupes the prebuilts.

    Args:
      root (Path): The root directory.
      paths (List[str]): File paths (relative to root) to be uploaded.
      uri: The Google Storage URI to upload the paths to. Their path at the URI
          will match their path relative to the root. E.g., foo/bar.tbz2 will be
          uploaded to <uri>/foo/bar.tbz2.
    """
    with self.m.step.nest('upload prebuilt blobs to GS'):
      sync_root = self.m.path.mkdtemp(prefix='prebuilts')
      symlink_tree = self.m.file.symlink_tree(sync_root)
      for relative_path in paths:
        local_path = root.join(relative_path)
        sync_path = symlink_tree.root.join(relative_path)
        symlink_tree.register_link(local_path, sync_path)
      symlink_tree.create_links('link files to upload')
      self.m.gsutil(['rsync', '-r', symlink_tree.root, uri],
                    parallel_upload=True, multithreaded=True)

  def upload_target_prebuilts(self, target, kind, gs_bucket, private=True):
    """Upload binary prebuilts for the build target to Google Storage.

    Determines what to upload, uploads it, and points Portage to the upload URI.
    This step works entirely within the workspace checkout.

    Args:
      target (BuildTarget): The build target to upload prebuilts for.
      kind (BuilderConfig.Id.Type): Kind of prebuilts to upload.
      gs_bucket (str): Google storage bucket to upload prebuilts to.
      private (bool): Whether or not the target prebuilts are private.
    """
    binhost_key = self._binhost_key(kind)
    with self.m.step.nest('upload prebuilts'):
      upload_uri = self._prebuilts_uri(target, kind, gs_bucket)
      upload_root, upload_paths = self._prepare_binhost_uploads(
          target, upload_uri)
      self._upload(upload_root, upload_paths, upload_uri)
      self._set_binhost(target, private, binhost_key, upload_uri)
