# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS prebuilts to Google Storage."""

import os

from recipe_engine import recipe_api

from PB.chromite.api import binhost


class CrosPrebuiltsApi(recipe_api.RecipeApi):
  """A module for uploading package prebuilts."""

  def __init__(self, prebuilts_gs_bucket, **kwargs):
    super(CrosPrebuiltsApi, self).__init__(**kwargs)
    self._gs_bucket = prebuilts_gs_bucket

  def _prebuilts_uri(self, target, kind):
    """Determine the GS URI to upload prebuilts.
    Args:
      target (BuildTarget): The build target.
      kind (str): The kind of prebuilts, e.g. "postsubmit"

    Returns:
      The full GS URI in which to upload prebuilts.
    """
    version = self.m.cros_version.read_workspace_version()
    return '%s/board/%s/%s-%s/packages' % (self._gs_bucket, target.name, kind,
                                           version)

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
      pbu_request = binhost.PrepareBinhostUploadsRequest()
      pbu_request.build_target.CopyFrom(target)
      pbu_request.uri = uri
      pbu_response = self.m.cros_build_api.call_proto(
          'chromite.api.BinhostService/PrepareBinhostUploads', pbu_request,
          test_output_data=self.test_api.prepare_binhost_uploads_response)
      upload_root = self.m.path.abs_to_path(pbu_response.uploads_dir)
      upload_paths = [ut.path for ut in pbu_response.upload_targets]
      return upload_root, upload_paths

  def _set_binhost(self, target, private, key, uri):
    """Set the target's Portage binhost to point to the given URI.

    This function updates a conf file within the target's overlay, commits the
    change, and pushes it.

    Args:
      target (BuildTarget): Build target to update the binhost for.
      private (bool): Whether the target's binhost is private.
      key (str): The binhost key, e.g. POSTSUBMIT_BINHOST.
      uri (str): The new binhost URI.
    """
    with self.m.step.nest('update binhost conf file'):
      sb_request = binhost.SetBinhostRequest()
      sb_request.build_target.CopyFrom(target)
      sb_request.private = private
      sb_request.key = binhost.BinhostKey.Value(key)
      sb_request.uri = uri

      sb_response = self.m.cros_build_api.call_proto(
          'chromite.api.BinhostService/SetBinhost', sb_request,
          test_output_data=self.test_api.set_binhost_response)
      binhost_path = self.m.path.abs_to_path(sb_response.output_file)
      binhost_data = self.m.file.read_text('read binhost conf', binhost_path)

      projects = self.m.repo.project_infos(projects=[binhost_path])
      assert len(projects) == 1, '%s must belong to 1 project' % binhost_path
      project = projects[0]

      # Staging doesn't have ACLs to push conf files for some targets.
      # TODO(crbug.com/952330): Figure out a way to cover this in staging.
      if not self.m.runtime.is_experimental:
        with self.m.context(
            cwd=self.m.cros_source.workspace_path.join(project.path)):
          self.m.git_txn.update_ref_write_file(
              project.remote, project.branch, 'Set %s=%s.' % (key, uri),
              binhost_path, binhost_data, automerge=True)

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
      self.m.gsutil(['rsync', symlink_tree.root, uri], parallel_upload=True,
                    multithreaded=True)

  def upload_target_prebuilts(self, target, kind, private=True):
    """Upload binary prebuilts for the build target to Google Storage.

    Determines what to upload, uploads it, and points Portage to the upload URI.
    This step works entirely within the workspace checkout.

    Args:
      target (BuildTarget): The build target to upload prebuilts for.
      kind (str): Label describing kind of prebuilts to upload (e.g. 'chrome').
      private (bool): Whether or not the target prebuilts are private.
    """
    with self.m.step.nest('upload prebuilts'):
      upload_uri = self._prebuilts_uri(target, kind)
      upload_root, upload_paths = self._prepare_binhost_uploads(
          target, upload_uri)
      self._upload(upload_root, upload_paths, upload_uri)
      binhost_key = '%s_BINHOST' % kind.upper()
      self._set_binhost(target, private, binhost_key, upload_uri)
