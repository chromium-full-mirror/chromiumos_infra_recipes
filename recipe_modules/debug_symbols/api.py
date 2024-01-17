# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for working with debug symbols."""

from recipe_engine import recipe_api


class DebugSymbols(recipe_api.RecipeApi):
  """Module for working with debug symbols."""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._gs_path = properties.gs_path
    self._worker_count = properties.worker_count
    self._retry_quota = properties.retry_quota
    self._staging = properties.staging
    self._dryrun = properties.dryrun

  def upload_debug_symbols(self, gs_path=None):
    """Upload debug symbols to the crash service."""
    staging = self._staging or self.m.cros_infra_config.is_staging
    gs_path = gs_path or self._gs_path

    with self.m.step.nest('validate properties'):
      # Check input parameters for basic validity.
      if not gs_path:
        raise recipe_api.StepFailure('gs_path is a required parameter')

    # Note this precludes running with 0 retries.
    retry_quota_param = ('-retry-quota %s' %
                         self._retry_quota if self._retry_quota else None)
    worker_count_param = ('-worker-count %s' %
                          self._worker_count if self._worker_count else None)
    staging_param = '-staging' if staging else None
    dryrun_param = '-dry-run=false' if not self._dryrun else None
    gs_debug_image_location = '%s/debug_breakpad.tar.xz' % (gs_path)
    gs_vmlinux_image_location = '%s/vmlinuz.tar.xz' % (gs_path)

    # The crash symbol collector service only returns information about
    # breakpad symbols that have been uploaded. Upload splitdebug first so that
    # we can rely on the status of the breakpad symbols to proxy the status of
    # splitdebug symbols. If the breakpad symbols aren't uploaded, we can
    # assume the splitdebug symbols aren't uploaded either.
    with self.m.failures.ignore_exceptions():
      if not staging:
        with self.m.step.nest('uploading splitdebug') as pres:
          # CLI invocation of upload_debug_symbols golang binary.
          cmd = list(
              filter(None, [
                  'upload',
                  '-gs-path',
                  gs_path,
                  '-data-type=splitdebug',
                  worker_count_param,
                  retry_quota_param,
                  staging_param,
                  dryrun_param,
              ]))
          if not staging:
            step_data = self.m.gobin.call(
                'upload_debug_symbols', cmd,
                stdout=self.m.raw_io.output_text(name='stdout',
                                                 add_output_log=True))
            pres.logs['upload logs'] = step_data.stdout

    with self.m.step.nest('uploading breakpad') as pres:
      # CLI invocation of upload_debug_symbols golang binary.
      cmd = list(
          filter(None, [
              'upload',
              '-gs-path',
              gs_debug_image_location,
              worker_count_param,
              retry_quota_param,
              staging_param,
              dryrun_param,
          ]))
      step_data = self.m.gobin.call(
          'upload_debug_symbols', cmd,
          stdout=self.m.raw_io.output_text(name='stdout', add_output_log=True))
      pres.logs['upload logs'] = step_data.stdout

    with self.m.failures.ignore_exceptions():
      if not staging:
        with self.m.step.nest('uploading vmlinux') as pres:
          # CLI invocation of upload_debug_symbols golang binary.
          cmd = list(
              filter(None, [
                  'upload',
                  '-gs-path',
                  gs_vmlinux_image_location,
                  '-data-type=vmlinux',
                  worker_count_param,
                  retry_quota_param,
                  staging_param,
                  dryrun_param,
              ]))
          if not staging:
            step_data = self.m.gobin.call(
                'upload_debug_symbols', cmd,
                stdout=self.m.raw_io.output_text(name='stdout',
                                                 add_output_log=True))
            pres.logs['upload logs'] = step_data.stdout
