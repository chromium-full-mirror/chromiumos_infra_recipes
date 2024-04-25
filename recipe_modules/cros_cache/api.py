# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS cache."""
from recipe_engine import recipe_api


class CrosCacheApi(recipe_api.RecipeApi):
  """A module for CrOS-specific cache steps."""

  def create_cache_dir(self, directory):
    """Creates a working directory outside of recipe structure.

    Args:
      directory (Path):  Full path to directory to create.
    """
    return self.m.path.mkdtemp(prefix=directory)

  def write_and_upload_version(self, gs_bucket, version_file, version):
    """Write local version file and uploads to Google Storage.

    Args:
      gs_bucket (str): Target Google Storage bucket.
      version_file (str): Version file name.
      version (str): Version to write to tracking file.
    """
    version_file_path = self.m.path.cleanup_dir / version_file
    self.m.file.write_text('write version file', version_file_path, version)
    self.m.gsutil.upload(version_file_path, gs_bucket, version_file,
                         name='upload {}'.format(version_file))
    self.m.easy.set_properties_step(**{version_file: version})
