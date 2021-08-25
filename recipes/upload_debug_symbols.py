# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for uploading debug symbols to the crash service."""

DEPS = [
    'recipe_engine/context',
    'recipe_engine/cipd',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'cros_infra_config',
]

from PB.recipes.chromeos.upload_debug_symbols import UploadDebugSymbolsProperties

PROPERTIES = UploadDebugSymbolsProperties


def ensure_cipd_package(api, cipd_package_location, cipd_ref, package_name):
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
  with api.step.nest('ensure ' + package_name):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')

      pkgs = api.cipd.EnsureFile()
      pkgs.add_package(cipd_package_location, cipd_ref)
      api.cipd.ensure(cipd_dir, pkgs)

      return cipd_dir.join(package_name)


def RunSteps(api, properties):
  """Invoke the upload debug symbols builder."""
  staging = properties.is_staging or api.cros_infra_config.is_staging
  # This is the name of the package as known buy the CIPD package system.
  with api.step.nest('fetch CIPD packages'):
    with api.context(infra_steps=True):
      # The full location of the package is needed to fetch the binary.
      cipd_package_location = ('chromiumos/infra/'
                               'upload_debug_symbols/${platform}')

      # Specify which instance of the package to pull. Default to prod.
      cipd_ref = ('prod' or properties.cipd_ref)

      # Retrieve the binary and store it locally.
      upload_debug_symbols_path = ensure_cipd_package(
          api,
          cipd_package_location,
          cipd_ref,
          'upload_debug_symbols',
      )

  # CLI invocation of upload_debug_symbols golang binary.
  cmd = [
      upload_debug_symbols_path,
      properties.google_storage_path,
      properties.worker_count,
      properties.retry_count,
      staging,
      properties.dry_run,
  ]

  # Raise failures as InfraFailures rather than StepFailures
  with api.context(infra_steps=True):
    return api.step('upload debug symbols', cmd, stdout=api.raw_io.output())


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              "cipd_ref": 'prod',
              "google_storage_path": 'gs-test',
              "worker_count": 90,
              "retry_count": 90,
              "is_staging": True,
              "dry_run": False,
          }),
  )
