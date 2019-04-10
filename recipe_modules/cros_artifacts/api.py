# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS build artifacts to Google Storage."""

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
      self.m.build_api.call_proto(
          endpoint, bundle_request,
          test_output_data=self.test_api.bundle_response)

  def upload_artifacts(self, name, target, kind, artifacts):
    """Bundle and upload the given artifacts for the given build target.

    Args:
      name (str): The step name.
      target (BuildTarget): The build target with artifacts of interest.
      kind (str): The kind of artifacts being uploaded, e.g. 'postsubmit'.
          This affects where the artifacts are placed in Google Storage.
      artifacts (list[ArtifactTypes]): List of artifacts
          to upload. See build config for options.

    Returns:
      tuple(str, str): GS bucket and GS path at which artifacts were uploaded.
    """
    with self.m.step.nest(name):
      staging_root = self.m.path.mkdtemp(prefix='artifacts')
      for artifact in artifacts:
        self._bundle_artifact(artifact, target, staging_root)
      upload_bucket = 'gs://chromeos-image-archive'
      upload_path = self._artifacts_gs_path(target, kind)
      upload_uri = '%s/%s' % (upload_bucket, upload_path)
      self.m.gsutil(['rsync', staging_root, upload_uri], parallel_upload=True,
                    multithreaded=True)
      return upload_bucket, upload_path
