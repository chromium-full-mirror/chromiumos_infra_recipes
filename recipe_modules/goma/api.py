# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with goma."""

from recipe_engine import recipe_api

from PB.chromiumos import common


class GomaApi(recipe_api.RecipeApi):
  """A module for working with goma."""

  def __init__(self, properties, *args, **kwargs):
    super(GomaApi, self).__init__(*args, **kwargs)
    self._client_version = properties.client_version or 'latest'
    self._goma_approach = properties.goma_approach or common.GomaConfig.DEFAULT

  def initialize(self):
    self._goma_dir = None

  @property
  def goma_client_json(self):
    return self.m.path.join('/creds/service_accounts',
                            'service-account-%s.json' % 'goma-client')

  @property
  def goma_dir(self):
    """Lazily fetches the goma client and returns its path."""
    if self._goma_dir:
      return self._goma_dir
    self._ensure_goma()
    return self._goma_dir

  @property
  def goma_approach(self):
    return self._goma_approach

  def _ensure_goma(self):
    """Ensure that the goma client is installed."""
    with self.m.step.nest('ensure goma client'), self.m.context(
        infra_steps=True):
      goma_dir = self.m.path['start_dir'].join('cipd', 'goma')
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('infra_internal/goma/client/${platform}',
                       str(self._client_version))
      self.m.cipd.ensure(goma_dir, pkgs)
      self._goma_dir = goma_dir

  def process_artifacts(self, install_pkg_response, goma_log_dir,
                        build_target_name):
    """Process goma artifacts, uploading to gsutil if they exist.

    Args:
      install_pkg_response (chromite.api.InstallPackagesResponse): May contain
        goma artifacts.
      goma_log_dir (str): Log directory that contains the goma log files.
      build_target_name (str): Build target string.

    Returns: (str) the gs_path used when writing to the goma GS bucket or None
      if there were no artifacts to process.
    """
    with self.m.step.nest('process_goma_artifacts') as step:
      if install_pkg_response.HasField('goma_artifacts') and goma_log_dir:
        with self.m.context(cwd=self.m.path.abs_to_path(goma_log_dir)):
          # destination gs_path is based on date and build_target name.
          today = self.m.time.utcnow()
          gs_path = '%s/%s' % (
              today.strftime('%Y/%m/%d'), build_target_name)
          gs_bucket = 'chrome-goma-log'
          step.presentation.logs['gs_path'] = gs_path
          num_logs_uploaded = 0
          for log_file in install_pkg_response.goma_artifacts.log_files:
            self.m.gsutil.upload(log_file, gs_bucket, gs_path)
            num_logs_uploaded += 1
          step.presentation.logs['num_logs_uploaded'] = str(num_logs_uploaded)
          return gs_path
      else:
        step.presentation.logs['NoGomaArtifacts'] = [
            str(install_pkg_response.goma_artifacts)
        ]
        return None
