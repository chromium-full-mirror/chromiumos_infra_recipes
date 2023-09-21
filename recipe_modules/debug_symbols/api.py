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
    self._cipd_ref = properties.cipd_ref
    self._gs_path = properties.gs_path
    self._worker_count = properties.worker_count
    self._retry_quota = properties.retry_quota
    self._staging = properties.staging
    self._dryrun = properties.dryrun

  def ensure_cipd_package(self, cipd_package_location, cipd_ref, package_name):
    """Use the recipe_engine CIPD api to fetch and store the package locally.

    Args:
      cipd_package_location (str): CIPD location where the package is stored.
        E.g. chromiumos/infra/upload_debug_symbols/${platform}
      cipd_ref (String): Instance of package to use. Typically, prod or staging.
      package_name (String): Name of package minus extra location information.
        E.g. upload_debug_symbols, manifest_doctor, branch_util.

    Returns:
      Path: Path to the locally stored package.
    """
    with self.m.step.nest('ensure ' + package_name):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(cipd_package_location, cipd_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)

        return cipd_dir.join(package_name)

  def upload_debug_symbols(self, gs_path=None):
    """Upload debug symbols to the crash service."""
    staging = self._staging or self.m.cros_infra_config.is_staging
    gs_path = gs_path or self._gs_path

    with self.m.step.nest('validate properties'):
      # Check input parameters for basic validity.
      if not gs_path:
        raise recipe_api.StepFailure('gs_path is a required parameter')

    # This is the name of the package as known buy the CIPD package system.
    with self.m.step.nest('fetch CIPD packages'):
      with self.m.context(infra_steps=True):
        # The full location of the package is needed to fetch the binary.
        cipd_package_location = ('chromiumos/infra/'
                                 'upload_debug_symbols/${platform}')

        # Specify which instance of the package to pull.
        default_cipd_ref = 'staging' if staging else 'prod'
        cipd_ref = self._cipd_ref or default_cipd_ref

        # Retrieve the binary and store it locally.
        upload_debug_symbols_path = self.ensure_cipd_package(
            cipd_package_location,
            cipd_ref,
            'upload_debug_symbols',
        )

    # Note this precludes running with 0 retries.
    retry_quota_param = ('-retry-quota %s' %
                         self._retry_quota if self._retry_quota else None)
    worker_count_param = ('-worker-count %s' %
                          self._worker_count if self._worker_count else None)
    staging_param = '-staging' if staging else None
    dryrun_param = '-dry-run=false' if not self._dryrun else None
    gs_debug_image_location = '%s/debug_breakpad.tar.xz' % (gs_path)
    gs_vmlinux_image_location = '%s/vmlinuz.tar.xz' % (gs_path)

    with self.m.step.nest('uploading breakpad') as pres:
      # CLI invocation of upload_debug_symbols golang binary.
      cmd = list(
          filter(None, [
              upload_debug_symbols_path,
              'upload',
              '-gs-path',
              gs_debug_image_location,
              worker_count_param,
              retry_quota_param,
              staging_param,
              dryrun_param,
          ]))
      step_data = self.m.step(
          'call upload go binary', cmd,
          stdout=self.m.raw_io.output_text(name='stdout', add_output_log=True))
      pres.logs['upload logs'] = step_data.stdout

    with self.m.failures.ignore_exceptions():
      if not staging:
        with self.m.step.nest('uploading vmlinux') as pres:
          # CLI invocation of upload_debug_symbols golang binary.
          cmd = list(
              filter(None, [
                  upload_debug_symbols_path,
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
            step_data = self.m.step(
                'call upload go binary', cmd,
                stdout=self.m.raw_io.output_text(name='stdout',
                                                 add_output_log=True))
            pres.logs['upload logs'] = step_data.stdout
