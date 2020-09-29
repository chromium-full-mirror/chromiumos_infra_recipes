# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS cache."""

import datetime
import json
import os

from recipe_engine.recipe_api import RecipeApi, StepFailure
from recipe_engine.util import exponential_retry

# Number of seconds to wait on gsutil rsync.
gsutil_timeout_seconds = 30 * 60


class CrosCacheApi(RecipeApi):
  """A module for CrOS-specific cache steps."""

  def __init__(self, *args, **kwargs):
    super(CrosCacheApi, self).__init__(*args, **kwargs)

  def create_cache_dir(self, directory):
    """Creates a working directory outside of recipe structure.

    Args:
      directory (Path):  Full path to directory to create.
    """
    return self.m.path.mkdtemp(prefix=directory)

  def package_source(self, filename, source_path):
    """Packages up the current checkout of source to a tar file for cache usage.

    Args:
      filename (str): Base filename to create.
      source_path (Path):  Location of the repo checkout to package.

    Returns:
      archive_file (Path): Path to the created archive file.
      version_file (Path): Path to the created version file.
    """
    with self.m.step.nest('tar up source repo checkout') as presentation:
      if self.m.path.exists(source_path):
        archive_path = self.m.path.mkdtemp(prefix='source_cache')
        version_file = archive_path.join('version.txt')
        self.m.file.write_raw('write version file', version_file, filename)
        archive_file = archive_path.join(filename)
        presentation.step_text = ('archive file: %s' % filename)
        archive_cmd = [
            'tar', '--use-compress-program=pigz', '-cf', archive_file, '.'
        ]
        self.m.step('packaging via %s for cache' % archive_cmd, archive_cmd,
                    infra_step=True)
      else:
        raise StepFailure('source directory does not exist')
      return archive_file, version_file

  def upload_artifact(self, gs_bucket, upload_file):
    """Uploads cache and version file to Google Storage.

    Args:
      gs_bucket (str): Target Google Storage bucket.
      upload_file (Path):  Location of cache artifact file to upload.
    """
    upload_uri = 'gs://%s/%s' % (gs_bucket, 'chromeos-ci')
    # TODO: Refactor retry logic to utilize helper function to simplify
    # readabiltiy and reuse.
    for retries in range(3):
      try:
        self.m.gsutil(['cp', upload_file, upload_uri],
                      timeout=gsutil_timeout_seconds)
        break
      except StepFailure as ex:
        if ex.had_timeout and retries < 2:
          continue
        else:
          raise
