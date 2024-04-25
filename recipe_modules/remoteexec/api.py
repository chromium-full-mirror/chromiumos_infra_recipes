# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with re-client for remote execution."""

import json
from typing import List, Optional

from PB.chromite.api.sysroot import InstallPackagesResponse
from recipe_engine import recipe_api


class RemoteexecApi(recipe_api.RecipeApi):
  """A module for working with re-client for remote execution."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._reclient_version = properties.reclient_version
    self._reproxy_cfg_file = properties.reproxy_cfg_file
    self._enable_logs_upload = properties.enable_logs_upload
    self._reclient_dir = None

  @property
  def reclient_dir(self):
    """Fetches the reclient directory and returns its path."""
    if self._reclient_dir is None:
      self._ensure_reclient()
    return self._reclient_dir

  @property
  def reproxy_cfg_file(self):
    return self._reproxy_cfg_file

  @property
  def enable_logs_upload(self):
    return self._enable_logs_upload

  def _ensure_reclient(self):
    with self.m.step.nest('ensure reclient binaries'), self.m.context(
        infra_steps=True):
      reclient_dir = self.m.path.start_dir.joinpath('cipd', 'rbe')
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('infra/rbe/client/${platform}',
                       str(self._reclient_version))
      self.m.cipd.ensure(reclient_dir, pkgs)
      self._reclient_dir = reclient_dir

  def process_artifacts(
      self,
      install_pkg_response: InstallPackagesResponse,
      log_dir: str,
      build_target_name: str,
      is_staging: bool = False,
  ) -> Optional[List[str]]:
    """Process remoteexec artifacts, uploading to Google Cloud Storage if they exist.

    Args:
      install_pkg_response: Result from InstallPackage call. May contain
        remoteexec artifacts.
      log_dir (str): Log directory that contains the artifacts.
      build_target_name (str): Build target string.
      is_staging (bool): If being run in staging environment instead of prod.
    """
    if not self.enable_logs_upload:
      return None

    # Skip if we don't have remoteexec artifacts and a remoteexec_log dir for them.
    with self.m.step.nest('process_remoteexec_artifacts') as presentation:
      presentation.logs['remoteexec_artifacts'] = str(
          install_pkg_response.remoteexec_artifacts)
      presentation.logs['log_dir'] = str(log_dir)

      if (not install_pkg_response.HasField('remoteexec_artifacts') or
          not log_dir):
        return None

      with self.m.context(cwd=self.m.path.abs_to_path(log_dir)):
        # destination gs_path is based on date, build_target & bot_id name.
        today = self.m.time.utcnow()
        gs_path_base = self.m.path.join(
            today.strftime('%Y/%m/%d'),
            self.m.properties.get('bot_id', build_target_name),
        )
        gs_bucket = ('staging-chromeos-reclient-logs'
                     if is_staging else 'chromeos-reclient-logs')
        presentation.logs['gs_bucket'] = gs_bucket
        presentation.logs['gs_path'] = gs_path_base
        num_logs_uploaded = 0
        builder_id = self.m.buildbucket.build.builder
        metadata = {
            'x-goog-meta-builderinfo':
                json.dumps(
                    {
                        'is_cros': True,
                        'bot_id': self.m.properties.get('bot_id', ''),
                        'build_id': self.m.buildbucket.build.id,
                        'builder_id': {
                            'project': builder_id.project,
                            'bucket': builder_id.bucket,
                            'builder': builder_id.builder,
                        },
                        'build_target_name': build_target_name,
                    },
                    sort_keys=True,
                )
        }

        uploaded_files = []
        for log_file in install_pkg_response.remoteexec_artifacts.log_files:
          basename = self.m.path.basename(log_file)
          dirname = self.m.path.basename(self.m.path.dirname(log_file))
          gs_path = self.m.path.join(gs_path_base, dirname, basename)
          link_name = 'gsutil.upload'
          upload_result = self.m.gsutil.upload(
              log_file,
              gs_bucket,
              gs_path,
              metadata=metadata,
              link_name=link_name,
          )
          presentation.links[basename] = upload_result.presentation.links[
              link_name]
          uploaded_files.append(basename)
          num_logs_uploaded += 1

        presentation.logs['num_logs_uploaded'] = str(num_logs_uploaded)
        return uploaded_files
