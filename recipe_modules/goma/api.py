# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with goma."""

import collections
import json
import os
from typing import Optional, Tuple

from google.protobuf import json_format
from PB.chromite.api import sysroot as sysroot_pb2
from PB.chromiumos import common as common_pb2
from PB.goma import compile_events as compile_events_pb2
from PB.goma import counterz as counterz_pb2
from PB.goma import goma_stats as goma_stats_pb2
from recipe_engine import config_types
from recipe_engine import recipe_api

_BQUPLOAD_VERSION = 'git_revision:643892f957c8e106dff793468101f2ecfc31abb7'

_GOMA_COMPILER_PROXY_LOG_URL_TEMPLATE = (
    'https://chromium-build-stats.appspot.com/compiler_proxy_log/%s')
_GOMA_NINJA_LOG_URL_TEMPLATE = (
    'https://chromium-build-stats.appspot.com/ninja_log/%s')

# GsDestination stores GS bucket and path.
GsDestination = collections.namedtuple('GsDestination', ['bucket', 'path'])

# GomaResults includes GSDestination fields.
GomaResults = collections.namedtuple('GomaResults', ['bucket', 'path'])


class GomaApi(recipe_api.RecipeApi):
  """A module for working with goma."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._client_version = properties.client_version or 'release'
    self._goma_approach = (
        properties.goma_approach or common_pb2.GomaConfig.RBE_CHROMEOS)
    self._upload_goma_logs = not properties.disable_goma_logs_upload
    self._upload_stats_counterz = (not properties.disable_stats_counterz_upload)
    self._bigquery_project_id = properties.bigquery_project_id or 'goma-logs'
    self._bigquery_dataset_id = (
        properties.bigquery_dataset_id or 'client_events')
    self._bigquery_table_name = (
        properties.bigquery_table_name or 'compile_events')
    self._bigquery_verbose = properties.bigquery_verbose

  def initialize(self, also_bq_upload=False):
    self._also_bq_upload = also_bq_upload
    self._goma_dir = None

  @property
  def goma_dir(self):
    """Lazily fetches the goma client and returns its path."""
    if self._goma_approach <= common_pb2.GomaConfig.DEFAULT:
      return None
    if self._goma_dir:
      return self._goma_dir
    self._ensure_goma()
    return self._goma_dir

  @property
  def goma_approach(self) -> common_pb2.GomaConfig.GomaApproach:
    return self._goma_approach

  @property
  def default_bqupload_dir(self) -> config_types.Path:
    return self.m.path['cache'].join('goma', 'bqupload')

  def _ensure_goma(self) -> None:
    """Ensure that the goma client is installed."""
    with self.m.step.nest('ensure goma client'), self.m.context(
        infra_steps=True):
      goma_dir = self.m.path['start_dir'].join('cipd', 'goma')
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('infra_internal/goma/client/${platform}',
                       str(self._client_version))
      self.m.cipd.ensure(goma_dir, pkgs)
      self._goma_dir = goma_dir
    if self._also_bq_upload:
      with self.m.step.nest('ensure bqupload client'), self.m.context(
          infra_steps=True):
        # Download bqupload.
        bqupload_pkgs = self.m.cipd.EnsureFile()
        bqupload_pkgs.add_package('infra/tools/bqupload/${platform}',
                                  _BQUPLOAD_VERSION)
        self.m.cipd.ensure(self.default_bqupload_dir, bqupload_pkgs)

  def process_artifacts(
      self, install_pkg_response: sysroot_pb2.InstallPackagesResponse,
      goma_log_dir: str, build_target_name: str,
      is_staging: bool = False) -> Optional[Tuple[GomaResults]]:
    """Process goma artifacts, uploading to gsutil if they exist.

    Args:
      install_pkg_response: May contain goma artifacts.
      goma_log_dir: Log directory that contains the goma artifacts.
      build_target_name: Build target string.
      is_staging: If being run in staging environment instead of prod.

    Returns:
      Tuple containing the GS bucket and path used to write log files.
        None is returned if there were no artifacts to process.
    """
    # Skip if config has disabled this step entirely.
    if not self._upload_goma_logs and not self._upload_stats_counterz:
      return None

    # Skip if we don't have goma artifacts and a goma_log dir for them.
    if (not install_pkg_response.HasField('goma_artifacts') or
        not goma_log_dir):
      with self.m.step.nest('process_goma_artifacts') as presentation:
        presentation.logs['NoGomaArtifacts'] = str(
            install_pkg_response.goma_artifacts)
      return None

    if self._upload_stats_counterz:
      self._process_counterz_and_stats(install_pkg_response, goma_log_dir,
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
    # Based on GsDestination, create and return GomaResults.
    return GomaResults(gs_bucket, gs_path)

  def _process_counterz_and_stats(
      self, install_pkg_response: sysroot_pb2.InstallPackagesResponse,
      goma_log_dir: str, is_staging: bool) -> None:
    """Process counterz and stats, uploading data to BigQuery.

    Args:
      install_pkg_response): May contain goma artifacts.
      goma_log_dir: Log directory that contains the goma log files.
      is_staging: If being run in staging environment instead of prod.
    """
    with self.m.step.nest('process_goma_counterz_stats') as presentation:
      if install_pkg_response.HasField('goma_artifacts') and goma_log_dir:
        stats_filename = None
        counterz_filename = None
        compile_event = compile_events_pb2.CompileEvent()
        compile_event.build_id = self.m.buildbucket.build.id
        # Process stats file.
        if install_pkg_response.goma_artifacts.stats_file:
          # Populate MachineInfo in GomaStats since it has an enum type, which
          # is important to display for BigQuery type conversion.
          test_goma_stats_proto = goma_stats_pb2.GomaStats(
              time_stats=goma_stats_pb2.TimeStats(uptime=1234),
              machine_info=goma_stats_pb2.MachineInfo(
                  goma_revision='953240d2c4512d99191488cc98fc6f99@1586141662',
                  os=goma_stats_pb2.MachineInfo.OSType.Value('LINUX'), ncpus=32,
                  memory_size=67242942464))
          stats_filename = os.path.join(
              goma_log_dir, install_pkg_response.goma_artifacts.stats_file)
          stats_bin = self.m.file.read_raw(
              'read_stats_proto', stats_filename,
              test_data=test_goma_stats_proto.SerializeToString())
          compile_event.stats.ParseFromString(stats_bin)
        # Process counterz file.
        if install_pkg_response.goma_artifacts.counterz_file:
          test_counterz_proto = counterz_pb2.CounterzStats()
          counterz_filename = os.path.join(
              goma_log_dir, install_pkg_response.goma_artifacts.counterz_file)
          counterz_bin = self.m.file.read_raw(
              'read_counterz_proto', counterz_filename,
              test_data=test_counterz_proto.SerializeToString())
          compile_event.counterz_stats.ParseFromString(counterz_bin)
        if stats_filename or counterz_filename:
          presentation.logs['compile_event'] = str(compile_event)
          json_message = json_format.MessageToJson(
              compile_event, preserving_proto_field_name=True)
          # Call bq-insert support tool.
          support_input = {
              'project_id': self._bigquery_project_id,
              'dataset_id': self._bigquery_dataset_id,
              'table_name': self._bigquery_table_name,
              'write_data': True,
              'compile_event': json_message,
              'verbose': self._bigquery_verbose
          }
          test_output_data = {}
          if self._bigquery_verbose:
            presentation.logs['support_input'] = json.dumps(
                support_input, separators=(',', ':'), sort_keys=True)
            presentation.logs['compile_event_json'] = json.dumps(
                json_message, separators=(',', ': '), sort_keys=True)
          # TODO(crbug.com/1041899): Replace this disable-in-staging with a
          # BigQuery upload that staging has permission so that staging tests
          # the same flow and so that we have a non-prod BigQuery table to do
          # use for pre-prod integration tests.
          if not is_staging:
            self.m.support.call('bq-insert', support_input,
                                test_output_data=test_output_data,
                                raise_on_failure=False)

  def _process_log_files(
      self, install_pkg_response: sysroot_pb2.InstallPackagesResponse,
      goma_log_dir: str, build_target_name: str,
      is_staging: bool) -> Tuple[GsDestination]:
    """Upload goma log files specified by the response with gsutil.

    Args:
      install_pkg_response: May contain goma artifacts.
      goma_log_dir: Log directory that contains the goma log files.
      build_target_name: Build target string.
      is_staging: If being run in staging environment instead of prod.

    Returns:
      Tuple containing the bucket and gs_path used when writing to the goma GS
      bucket.
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
                    }, sort_keys=True)
        }
        for log_file in install_pkg_response.goma_artifacts.log_files:
          basename = self.m.path.basename(log_file)
          gs_path = self.m.path.join(gs_path_base, basename)
          self.m.gsutil.upload(log_file, gs_bucket, gs_path, metadata=metadata)
          num_logs_uploaded += 1

          if basename.startswith('ninja_log'):
            presentation.links['ninja_log'] = \
                _GOMA_NINJA_LOG_URL_TEMPLATE % gs_path
          if basename.startswith('compiler_proxy'):
            presentation.links['compiler_proxy'] = \
                _GOMA_COMPILER_PROXY_LOG_URL_TEMPLATE % gs_path

        presentation.logs['num_logs_uploaded'] = str(num_logs_uploaded)
        return GsDestination(gs_bucket, gs_path_base)
