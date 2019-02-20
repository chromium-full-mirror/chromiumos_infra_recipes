# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from recipe_engine import recipe_api

# GS BUCKET in which to archive build artifacts.
ARCHIVE_BUCKET = 'chromeos-image-archive'

# Build api endpoint.
ARCHIVE_SERVICE = 'chromite.api.ArchiveService'

class ArtifactsApi(recipe_api.RecipeApi):
  """A module for artifact generation steps"""

  @property
  def _payload_path(self):
    return self.m.path['cleanup'].join('payload')

  def create_and_upload(self, step_name, build_report, artifacts):
    """Create and upload artifacts.

    Args:
      * step_name (str): Step name.
      * build_report (dict): Build report.
      * artifacts (list[str]): List of build artifacts.
    """
    endpoints = {
      'hw': 'CreateHwTestArchives',
      'vm': 'CreateVmTestArchives',
    }

    for artifact in artifacts:
      if artifact in endpoints.keys():
        self._create_and_upload(step_name, build_report, endpoints[artifact])
      else:
        raise ValueError('Unknown artifact type "%s"' % artifact)

  def _create_and_upload(self, step_name, build_report, endpoint):
    """Create and upload artifacts implementation.

    Args:
      * step_name (str): Step name.
      * build_report (dict): Build report.
      * endpoint (str): Build endpoint to invoke.
    """
    gs_buckets = self.m.properties.get('gs_buckets', [ARCHIVE_BUCKET])
    upload_path = _upload_path(build_report['build_target'], 
                               build_report['version'])

    with self.m.step.nest(step_name) as step_data:
      self.m.file.ensure_directory('create payload dir', self._payload_path)
      self._create_artifact(build_report, endpoint)
      self._upload(upload_path, gs_buckets)

    result = ["%s/%s" % (bucket, upload_path) for bucket in gs_buckets]
    return result

  def _create_artifact(self, build_report, endpoint):
    """Generate artifact using build api.

    Args:
      * step_name (str): Step name.
      * build_report (dict): Build report.
      * endpoint (str): Build endpoint to invoke.
    """
    self.m.build_api.call_json(
      service_method='%s/%s' % (ARCHIVE_SERVICE, endpoint),
      # input_dict represents a CreateArchiveRequest. See:
      # https://cs.chromium.org/chromium/src/third_party/chromite/api/proto/test_archive.proto
      input_dict={
          'build_target': {
              'name': build_report['build_target'],
          },
          'output_directory': str(self._payload_path),
      },
      # test_output_dict represents a CreateArchiveResponse. See:
      # https://cs.chromium.org/chromium/src/third_party/chromite/api/proto/test_archive.proto
      test_output_dict={
          'files': [
              {'path': '/path/to/artifact.tar'},
          ],
      })

  def _upload(self, upload_path, gs_buckets):
    """Uploads artifacts to Google storage.

    Args:
      * upload_path (str): GCS bucket path.
      * gs_buckets (list[str]): Buckets to upload artifacts.
    """
    for bucket in gs_buckets:
      self.m.gsutil.upload(self._payload_path, bucket, upload_path,
                           args=['-r'], multithreaded=True,
                           parallel_upload=True)

def _upload_path(build_target, version):
  """Get the base URL where artifacts are uploaded.

  Each build run stores its artifacts in a subdirectory of the base URI.
  We also have LATEST files under the base URI which help point to the
  latest build available for a given build target.

  Args:
  * build target (str): Build target.
  * version (str): Build version.

  Returns:
    Google Storage URI (i.e. 'gs://...') under which all archived files
      should be uploaded.  In other words, a path like a directory, even
      through GS has no real directories.
  """
  return os.path.join(build_target, version)
