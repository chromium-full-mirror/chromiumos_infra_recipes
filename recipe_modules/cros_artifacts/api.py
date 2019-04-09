# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for uploading CrOS build artifacts to Google Storage."""

from recipe_engine import recipe_api

from PB.chromite.api import artifacts

ARTIFACTS_SERVICE = 'chromite.api.ArtifactsService'

# Maps artifact type to corresponding build API endpoint.
# Note for maintainers: this dictionary must be kept in sync
# with the Starlark config.
ENDPOINTS_BY_ARTIFACT = {
    'image-zip': 'BundleImageZip',
    'test-update-payloads': 'BundleTestUpdatePayloads',
    'autotest-files': 'BundleAutotestFiles',
    'tast-files': 'BundleTastFiles',
    'pinned-guest-images': 'BundlePinnedGuestImages',
    'firmware': 'BundleFirmware',
    'ebuild-logs': 'BundleEbuildLogs',
}


class CrosArtifactsApi(recipe_api.RecipeApi):
  """A module for bundling and uploading build artifacts."""

  def _artifacts_uri(self, target, kind):
    version = self.m.cros_version.read_workspace_version()
    return 'gs://chromeos-image-archive/%s-%s/%s' % (target.name, kind, version)

  def _bundle_artifact(self, artifact, target, path):
    """Defer to the build API to bundle the given artifact."""
    with self.m.step.nest('bundle %s for upload' % artifact):
      assert artifact in ENDPOINTS_BY_ARTIFACT, (
          'Could not find build API endpoint for bundling artifact %s. '
          'You may need to sync the cros_artifacts recipe endpoint dictionary '
          'with the current build config.' % artifact)

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
      artifacts (list[str]): List of artifacts to upload. See build config
          for options.
    """
    with self.m.step.nest(name):
      staging_root = self.m.path.mkdtemp(prefix='artifacts')
      for artifact in artifacts:
        self._bundle_artifact(artifact, target, staging_root)
      upload_uri = self._artifacts_uri(target, kind)
      self.m.gsutil(['rsync', staging_root, upload_uri], parallel_upload=True,
                    multithreaded=True)
