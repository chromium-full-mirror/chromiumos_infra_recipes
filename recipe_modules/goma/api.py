# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with goma."""

import json
import os
from collections import namedtuple
from google.protobuf import json_format
from recipe_engine import recipe_api

from PB.chromiumos import common
from PB.goma.compile_events import CompileEvent
from PB.goma.counterz import CounterzStats
from PB.goma.goma_stats import GomaStats
from PB.goma.goma_stats import TimeStats

# GsDestination stores GS bucket and path.
GsDestination = namedtuple('GsDestination', ['bucket', 'path'])

# GomaResults includes GSDestination fields and BigQuery errors (str|None).
GomaResults = namedtuple('GomaResults', ['bucket', 'path', 'bq_errors'])

class GomaApi(recipe_api.RecipeApi):
  """A module for working with goma."""

  def __init__(self, properties, *args, **kwargs):
    super(GomaApi, self).__init__(*args, **kwargs)
    self._client_version = properties.client_version or 'latest'
    self._goma_approach = properties.goma_approach or common.GomaConfig.DEFAULT
    self._upload_goma_logs = not properties.disable_goma_logs_upload
    self._upload_stats_counterz = (
        not properties.disable_stats_counterz_upload)
    self._bigquery_project_id = properties.bigquery_project_id or 'goma-logs'
    self._bigquery_dataset_id = (
        properties.bigquery_dataset_id or 'client_events')
    self._bigquery_table_name = (
        properties.bigquery_table_name or 'compile_events')

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
      tuple[GomaResults]: tuple containing the GS bucket and path used to write
          log files and any BQ errors when updating stats/counterz. None is
          returned if there were no artifacts to process.
    """
    # Skip if config has disabled this step entirely.
    if not self._upload_goma_logs and not self._upload_stats_counterz:
      return None

    # Skip if we don't have goma artifacts and a goma_log dir for them.
    if (not install_pkg_response.HasField('goma_artifacts')
        or not goma_log_dir):
      with self.m.step.nest('process_goma_artifacts') as presentation:
        presentation.logs['NoGomaArtifacts'] = [
          str(install_pkg_response.goma_artifacts)
        ]
      return None

    bq_errors = None
    if self._upload_stats_counterz:
      bq_errors = self._process_counterz_and_stats(install_pkg_response,
                                                   goma_log_dir,
                                                   build_target_name,
                                                   is_staging)

    gs_tuple = None
    if self._upload_goma_logs:
      gs_tuple = self._process_log_files(install_pkg_response, goma_log_dir,
                                         build_target_name, is_staging)
    gs_bucket = None
    gs_path = None
    if gs_tuple:
      gs_bucket = gs_tuple.bucket
      gs_path = gs_tuple.path
    # Based on GsDestination and bq_erros, create and return GomaResults.
    return GomaResults(gs_bucket, gs_path, bq_errors)

  def _process_counterz_and_stats(self, install_pkg_response, goma_log_dir,
                        build_target_name, is_staging):
    """Process counterz and stats, uploading data to BigQuery.

    Args:
      install_pkg_response (chromite.api.InstallPackagesResponse): May contain
        goma artifacts.
      goma_log_dir (str): Log directory that contains the goma log files.
      build_target_name (str): Build target string.
      is_staging (bool): If being run in staging environment instead of prod.

    Returns:
      BigQuery error message (str) or None if no errors occurred.
    """
    with self.m.step.nest('process_goma_counterz_stats') as presentation:
      if install_pkg_response.HasField('goma_artifacts') and goma_log_dir:
        stats_filename = None
        counterz_filename = None
        compile_event = CompileEvent()
        compile_event.build_id = self.m.buildbucket.build.id
        # Process stats file.
        if install_pkg_response.goma_artifacts.stats_file:
          test_goma_stats_proto = GomaStats(time_stats=TimeStats(uptime=1234))
          stats_filename = os.path.join(
              goma_log_dir, install_pkg_response.goma_artifacts.stats_file)
          stats_bin = self.m.file.read_raw(
              'read_stats_proto', stats_filename,
              test_data=test_goma_stats_proto.SerializeToString())
          compile_event.stats.ParseFromString(stats_bin)
        # Process counterz file.
        if install_pkg_response.goma_artifacts.counterz_file:
          test_counterz_proto = CounterzStats()
          counterz_filename = os.path.join(
              goma_log_dir, install_pkg_response.goma_artifacts.counterz_file)
          counterz_bin = self.m.file.read_raw(
              'read_counterz_proto', counterz_filename,
              test_data=test_counterz_proto.SerializeToString())
          compile_event.counterz_stats.ParseFromString(counterz_bin)
        if stats_filename or counterz_filename:
          presentation.logs['compile_event'] = [str(compile_event)]
          # Call bq-insert support tool.
          input = {
              'project_id': self._bigquery_project_id,
              'dataset_id': self._bigquery_dataset_id,
              'table_name': self._bigquery_table_name,
              'write_data': True,
              'compile_event': json_format.MessageToJson(compile_event)
          }
          test_output_data = {}
          presentation.logs['support_input'] = [str(input)]
          # TODO(crbug.com/1041899): Replace this disable-in-staging with a
          # BigQuery upload that staging has permission so that staging tests
          # the same flow and so that we have a non-prod BigQuery table to do
          # use for pre-prod integration tests.
          if not is_staging:
            result = self.m.support.call('bq-insert', input,
                                         test_output_data=test_output_data)

    return None


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
          writing to the goma GS bucket
    """
    with self.m.step.nest('process_goma_logs') as presentation:
      with self.m.context(cwd=self.m.path.abs_to_path(goma_log_dir)):
        # destination gs_path is based on date and build_target name.
        today = self.m.time.utcnow()
        gs_path_base = self.m.path.join(
            today.strftime('%Y/%m/%d'),
            self.m.properties.get('bot_id', build_target_name))
        gs_bucket = ('staging-chrome-goma-log'
                     if is_staging else 'chrome-goma-log')
        presentation.logs['gs_bucket'] = gs_bucket
        presentation.logs['gs_path'] = gs_path_base
        num_logs_uploaded = 0
        builder_id = self.m.buildbucket.build.builder
        metadata = {
            'x-goog-meta-builderinfo':
                json.dumps({
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
          self.m.gsutil.upload(log_file, gs_bucket, gs_path, metadata=metadata)
          num_logs_uploaded += 1
        presentation.logs['num_logs_uploaded'] = str(num_logs_uploaded)
        return GsDestination(gs_bucket, gs_path_base)
