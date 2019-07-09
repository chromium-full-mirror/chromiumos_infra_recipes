# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS build artifacts to Google Storage."""

import os

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.chromite.api import artifacts
from PB.chromiumos.builder_config import BuilderConfig

ARTIFACTS_SERVICE = 'chromite.api.ArtifactsService'

# Maps artifact type to corresponding build API endpoint.
# Note for maintainers: this dictionary must be kept in sync
# with the Starlark config.
ENDPOINTS_BY_ARTIFACT = {
    BuilderConfig.Artifacts.IMAGE_ZIP: 'BundleImageZip',
    BuilderConfig.Artifacts.TEST_UPDATE_PAYLOAD: 'BundleTestUpdatePayloads',
    BuilderConfig.Artifacts.AUTOTEST_FILES: 'BundleAutotestFiles',
    BuilderConfig.Artifacts.TAST_FILES: 'BundleTastFiles',
    BuilderConfig.Artifacts.PINNED_GUEST_IMAGES: 'BundlePinnedGuestImages',
    BuilderConfig.Artifacts.FIRMWARE: 'BundleFirmware',
    BuilderConfig.Artifacts.EBUILD_LOGS: 'BundleEbuildLogs',
}


class CrosArtifactsApi(recipe_api.RecipeApi):
  """A module for bundling and uploading build artifacts."""

  def _get_endpoint(self, artifact):
    """Return the callable endpoint in ArtifactsService for this artifact.

    Args:
      artifact (ArtifactTypes): The artifact type to bundle.

    Returns:
      callable: The ArtifactsService endpoint.
    """
    assert artifact in ENDPOINTS_BY_ARTIFACT, (
        'Could not find build API endpoint for bundling artifact %s. '
        'You may need to sync the cros_artifacts recipe endpoint dictionary '
        'with the current build config.' % artifact_name)
    return getattr(self.m.cros_build_api.ArtifactsService,
                   ENDPOINTS_BY_ARTIFACT[artifact])

  def _bundle_artifact(self, artifact, target, path):
    """Defer to the build API to bundle the given artifact.

    Args:
      artifact (ArtifactTypes): The artifact to bundle.
      target (BuildTarget): The build target to bundle artifacts for.
      path (Path): Path to output artifact bundles.

    Returns:
      tuple(str, list[str]): Artifact name, list of artifact file paths
          relative to |path|.
    """
    artifact_name = BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)
    with self.m.step.nest('bundle %s for upload' % artifact_name):
      endpoint = self._get_endpoint(artifact)
      request = artifacts.BundleRequest(build_target=target,
                                        output_dir=str(path))
      response = endpoint(request, infra_step=True)

      artifact_files = [
          os.path.relpath(art.path, str(path)) for art in response.artifacts
      ]
      return artifact_name, artifact_files

  def artifacts_gs_path(self, target, kind):
    """Returns the GS path for artifacts of the given kind for the given target.

    The resulting path will NOT include the GS bucket.

    Args:
      target (BuildTarget): The target whose artifacts will be uploaded.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. Used as a descriptor in the GS path.

    Returns:
      The GS path at which artifacts should be uploaded.
    """
    label = BuilderConfig.Id.Type.Name(kind).lower().replace('_', '-')
    version = self.m.cros_version.read_workspace_version()
    build_id = self.m.buildbucket.build.id
    return '%s-%s/%s-%d' % (target.name, label, version, build_id)

  def upload_artifacts(self, target, kind, gs_bucket, artifacts, name=None):
    """Bundle and upload the given artifacts for the given build target.

    This function sets the "artifacts" output property to include the
    GS bucket, the path within that bucket, and a dict mapping artifact
    to a list of artifact paths (relative to the GS path) for each artifact
    type that was uploaded.

    Args:
      target (BuildTarget): The build target with artifacts of interest.
      kind (BuilderConfig.Id.Type): The kind of artifacts being uploaded,
          e.g. POSTSUBMIT. This affects where the artifacts are placed in
          Google Storage.
      gs_bucket (str): Google storage bucket to upload artifacts to.
      artifacts (list[ArtifactTypes]): List of artifacts
          to upload. See build config for options.
      name (str): The step name. Defaults to 'upload artifacts'.
    """
    with self.m.step.nest(name or 'upload artifacts'):
      staging_root = self.m.path.mkdtemp(prefix='artifacts')

      files_by_artifact = {}
      for artifact in artifacts:
        name, files = self._bundle_artifact(artifact, target, staging_root)
        files_by_artifact[name] = files

      gs_path = self.artifacts_gs_path(target, kind)
      upload_uri = 'gs://%s/%s' % (gs_bucket, gs_path)
      for retries in range(3):
        try:
          self.m.gsutil(['rsync', staging_root, upload_uri],
                        parallel_upload=True, multithreaded=True,
                        timeout=self.test_api.gsutil_timeout_seconds)
          break
        except recipe_api.StepFailure as ex:
          if ex.had_timeout and retries < 2:
            continue
          else:
            raise

      self.m.easy.set_property_step(
          'artifacts', {
              'gs_bucket': gs_bucket,
              'gs_path': gs_path,
              'files_by_artifact': files_by_artifact,
          }, step_name='output artifact GS paths')

  def download_artifact(self, build_payload, artifact, name=None):
    """Download the given artfiact from the given build payload.

    Args:
      build_payload (BuildPayload): Describes where the artifact is on GS.
      artifact (ArtifactType): The artifact to download.

    Returns:
      list[Path]: Paths to the files downloaded from GS.

    Raises:
      ValueError: If the artifact is not found in the build payload.
    """
    artifact_name = BuilderConfig.Artifacts.ArtifactTypes.Name(artifact)
    gs_bucket = build_payload.artifacts_gs_bucket
    gs_path = build_payload.artifacts_gs_path
    gs_file_names_by_artifact = json_format.MessageToDict(
        build_payload.files_by_artifact)
    gs_file_names = gs_file_names_by_artifact.get(artifact_name)
    if gs_file_names is None:
      raise ValueError('artifact %s not found in payload' % artifact_name)

    with self.m.step.nest(name or 'download %s' % artifact_name):
      download_root = self.m.path.mkdtemp(prefix='%s-' % artifact_name)
      download_paths = []
      for gs_file_name in gs_file_names:
        download_path = download_root.join(gs_file_name)
        self.m.gsutil.download(gs_bucket, os.path.join(gs_path, gs_file_name),
                               download_path)
        download_paths.append(download_path)
      return download_paths

  def download_artifacts(self, build_payload, artifacts, name=None):
    """Download the given artifacts from the given build payload.

    Args:
      build_payload (BuildPayload): Describes where build artifacts are on GS.
      artifacts (list[ArtifactTypes]): The artifact types to download.
      name (str): The step name. Defaults to 'download artifacts'.

    Returns:
      dict: Maps ArtifactType to list[Path] representing downloaded files.

    Raises:
      ValueError: If any artifact is not found in the build payload.
    """
    with self.m.step.nest(name or 'download artifacts'):
      return {
          artifact: self.download_artifact(build_payload, artifact)
          for artifact in artifacts
      }
