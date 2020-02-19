# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with goma."""

import json
from collections import namedtuple

from recipe_engine import recipe_api

from PB.chromiumos import common


GsDestination = namedtuple('GsDestination', ['bucket', 'path'])

class GomaApi(recipe_api.RecipeApi):
  """A module for working with goma."""

  def __init__(self, properties, *args, **kwargs):
    super(GomaApi, self).__init__(*args, **kwargs)
    self._client_version = properties.client_version or 'latest'
    self._goma_approach = properties.goma_approach or common.GomaConfig.DEFAULT
    self._upload_goma_logs = not properties.disable_goma_logs_upload

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
                        build_target_name, is_staging=False):
    """Process goma artifacts, uploading to gsutil if they exist.

    Args:
      install_pkg_response (chromite.api.InstallPackagesResponse): May contain
        goma artifacts.
      goma_log_dir (str): Log directory that contains the goma artifacts.
      build_target_name (str): Build target string.
      is_staging (bool): If being run in staging environment instead of prod.

    Returns:
      tuple[GsDestination]: tuple containing the bucket and gs_path used when
          writing to the goma GS bucket or None if there were no artifacts to
          process.
    """
    if not self._upload_goma_logs:
      return None
    return self._process_log_files(install_pkg_response, goma_log_dir,
                                  build_target_name, is_staging)

  def _process_log_files(self, install_pkg_response, goma_log_dir,
                        build_target_name, is_staging):
    """Upload goma log files specified by the response with gsutil.

    Args:
      install_pkg_response (chromite.api.InstallPackagesResponse): May contain
        goma artifacts.
      goma_log_dir (str): Log directory that contains the goma log files.
      build_target_name (str): Build target string.
      is_staging (bool): If being run in staging environment instead of prod.

    Returns:
      tuple[GsDestination]: tuple containing the bucket and gs_path used when
          writing to the goma GS bucket or None if there were no artifacts to
          process.
    """
    with self.m.step.nest('process_goma_artifacts') as step:
      if install_pkg_response.HasField('goma_artifacts') and goma_log_dir:
        with self.m.context(cwd=self.m.path.abs_to_path(goma_log_dir)):
          # destination gs_path is based on date and build_target name.
          today = self.m.time.utcnow()
          gs_path_base = self.m.path.join(
              today.strftime('%Y/%m/%d'),
              self.m.properties.get('bot_id', build_target_name))
          gs_bucket = ('staging-chrome-goma-log' if is_staging
                       else 'chrome-goma-log')
          step.presentation.logs['gs_bucket'] = gs_bucket
          step.presentation.logs['gs_path'] = gs_path_base
          num_logs_uploaded = 0
          builder_id = self.m.buildbucket.build.builder
          metadata = {
              'x-goog-meta-builderinfo': json.dumps({
                  'is_cros': True,
                  'bot_id': self.m.properties.get('bot_id', ''),
                  'build_id': self.m.buildbucket.build.id,
                  'builder_id': {
                      'project': builder_id.project,
                      'bucket': builder_id.bucket,
                      'builder': builder_id.builder,
                  },
                  'build_target_name': build_target_name,
              })
          }
          for log_file in install_pkg_response.goma_artifacts.log_files:
            gs_path = self.m.path.join(gs_path_base,
                                       self.m.path.basename(log_file))
            self.m.gsutil.upload(log_file, gs_bucket, gs_path,
                                 metadata=metadata)
            num_logs_uploaded += 1
          step.presentation.logs['num_logs_uploaded'] = str(num_logs_uploaded)
          return GsDestination(gs_bucket, gs_path_base)
      else:
        step.presentation.logs['NoGomaArtifacts'] = [
            str(install_pkg_response.goma_artifacts)
        ]
        return None
