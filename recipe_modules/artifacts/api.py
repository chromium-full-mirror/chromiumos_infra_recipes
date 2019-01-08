# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from recipe_engine import recipe_api

# GS BUCKET in which to archive build artifacts.
ARCHIVE_BUCKET='chromeos-image-archive'

class ArtifactsApi(recipe_api.RecipeApi):
  def upload(self, path, builder, build_id, gs_buckets):
    """Uploads artifacts to Google storage.

    Args:
      * path (Path): Directory containing artifacts.
      * builder (str): Builder name.
      * build_id (str): Buildbucket build id.
      * gs_buckets (list[str]): Buckets to upload artifacts.
    """
    if gs_buckets is None:
      gs_buckets = [ARCHIVE_BUCKET]

    for bucket in gs_buckets:
      upload_path = get_upload_path(builder, build_id)
      self.m.gsutil.upload(path, bucket, upload_path,
                           args=['-r'], multithreaded=True,
                           parallel_upload=True)

def get_upload_path(builder, build_id):
  """Get the base URL where artifacts from this builder are uploaded.

  Each build run stores its artifacts in a subdirectory of the base URI.
  We also have LATEST files under the base URI which help point to the
  latest build available for a given builder.

  Args:
	* builder (str): Builder name.
	* build_id (str): Buildbucket build id.

  Returns:
    Google Storage URI (i.e. 'gs://...') under which all archived files
      should be uploaded.  In other words, a path like a directory, even
      through GS has no real directories.
  """
  return os.path.join(builder, build_id)

