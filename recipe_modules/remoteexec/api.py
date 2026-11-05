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
    self._rbe_project = properties.rbe_project
    self._reapi_instance = properties.reapi_instance
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

  def set_rbe_instance_hook(self, gclient_solution):
    """Enable download_remoteexec_cfg gclient hook by setting gclient variables."""
    if not self._rbe_project:
      return

    with self.m.step.nest(
        'updating gclient solution with rbe_instance') as presentation:
      presentation.logs['rbe_project'] = self._rbe_project
      presentation.logs['reapi_instance'] = self._reapi_instance

      rbe_instance = "projects/%s/instances/%s" % (
          self._rbe_project, self._reapi_instance or "default_instance")
      if not gclient_solution.custom_vars:
        gclient_solution.custom_vars = {}
      gclient_solution.custom_vars['rbe_instance'] = rbe_instance

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
        # Destination GCS directory is based on date, tool, bot_id/build_target,
        # and build_id.
        today = self.m.time.utcnow()
        date_prefix = today.strftime('%Y/%m/%d')
        bot_or_target = self.m.properties.get('bot_id', build_target_name)
        builder_id = self.m.buildbucket.build.builder
        build_id = str(self.m.buildbucket.build.id)
        gs_bucket = ('staging-chromeos-build-logs'
                     if is_staging or builder_id.bucket == 'release.shadow' else
                     'chromeos-build-logs')
        presentation.logs['gs_bucket'] = gs_bucket
        presentation.logs['gs_path'] = date_prefix
        num_logs_uploaded = 0
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

        log_files = install_pkg_response.remoteexec_artifacts.log_files
        # Route ninja_log files to siso/ if any Siso logs are present in the
        # build artifacts, since ninja_log filenames lack a tool prefix.
        has_siso_logs = any(
            self._is_siso_log(
                dirname=self.m.path.basename(self.m.path.dirname(log_file)),
                basename=self.m.path.basename(log_file),
            ) for log_file in log_files)
        uploaded_files = []
        for log_file in log_files:
          basename = self.m.path.basename(log_file)
          dirname = self.m.path.basename(self.m.path.dirname(log_file))
          if (self._is_siso_log(dirname, basename) or
              (basename.startswith('ninja_log') and has_siso_logs)):
            tool = 'siso'
          else:
            tool = 'reclient'
          gs_path_parts = [date_prefix, tool, bot_or_target, build_id]
          if dirname:
            gs_path_parts.append(dirname)
          # End destination with '/' so gsutil cp skips storage.objects.list
          # (allowing builder service accounts to use objectCreators only).
          gs_dir = self.m.path.join(*gs_path_parts) + '/'
          link_name = 'gsutil.upload'
          upload_result = self.m.gsutil.upload(
              log_file,
              gs_bucket,
              gs_dir,
              metadata=metadata,
              link_name=link_name,
          )
          presentation.links[basename] = upload_result.presentation.links[
              link_name]
          uploaded_files.append(basename)
          num_logs_uploaded += 1

        presentation.logs['num_logs_uploaded'] = str(num_logs_uploaded)
        return uploaded_files

  @staticmethod
  def _is_siso_log(dirname: str, basename: str) -> bool:
    """Returns whether a log file is a Siso log based on its path."""
    return (dirname.startswith('siso-') or basename.startswith(
        ('siso', '.siso')))
