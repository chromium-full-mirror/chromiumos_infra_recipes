# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS build artifacts to Google Storage."""

import os

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

  def _artifacts_gs_path(self, target, kind):
    """Returns the GS path for artifacts of the given kind for the given target.

    The resulting path will NOT include the GS bucket.

    Args:
      target (BuildTarget): The target whose artifacts will be uploaded.
      kind (str): The kind of artifacts being uploaded, e.g., postsubmit.
          Used as a descriptor in the GS path.

    Returns:
      The GS path at which artifacts should be uploaded.
    """
    version = self.m.cros_version.read_workspace_version()
    return '%s-%s/%s' % (target.name, kind, version)

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
      assert artifact in ENDPOINTS_BY_ARTIFACT, (
          'Could not find build API endpoint for bundling artifact %s. '
          'You may need to sync the cros_artifacts recipe endpoint dictionary '
          'with the current build config.' % artifact_name)

      bundle_request = artifacts.BundleRequest()
      bundle_request.build_target.CopyFrom(target)
      bundle_request.output_dir = str(path)
      endpoint = '%s/%s' % (ARTIFACTS_SERVICE, ENDPOINTS_BY_ARTIFACT[artifact])
      bundle_response = self.m.build_api.call_proto(
          endpoint, bundle_request,
          test_output_data=self.test_api.bundle_response)
      artifact_files = [
          os.path.relpath(art.path, str(path))
          for art in bundle_response.artifacts
      ]
      return artifact_name, artifact_files

  def upload_artifacts(self, name, target, kind, artifacts):
    """Bundle and upload the given artifacts for the given build target.

    This function sets the "artifacts" output property to include the
    GS bucket, the path within that bucket, and a dict mapping artifact
    to a list of artifact paths (relative to the GS path) for each artifact
    type that was uploaded.

    Args:
      name (str): The step name.
      target (BuildTarget): The build target with artifacts of interest.
      kind (str): The kind of artifacts being uploaded, e.g. 'postsubmit'.
          This affects where the artifacts are placed in Google Storage.
      artifacts (list[ArtifactTypes]): List of artifacts
          to upload. See build config for options.
    """
    with self.m.step.nest(name):
      staging_root = self.m.path.mkdtemp(prefix='artifacts')

      files_by_artifact = {}
      for artifact in artifacts:
        name, files = self._bundle_artifact(artifact, target, staging_root)
        files_by_artifact[name] = files

      gs_bucket = 'gs://chromeos-image-archive'
      gs_path = self._artifacts_gs_path(target, kind)
      upload_uri = '%s/%s' % (gs_bucket, gs_path)
      self.m.gsutil(['rsync', staging_root, upload_uri], parallel_upload=True,
                    multithreaded=True)

      res = self.m.step('output artifact GS paths', cmd=None)
      res.presentation.properties['artifacts'] = {
          'gs_bucket': gs_bucket,
          'gs_path': gs_path,
          'files_by_artifact': files_by_artifact,
      }
