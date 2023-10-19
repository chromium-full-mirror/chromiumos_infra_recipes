# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with Go binaries built from infra/infra."""

import json
import traceback
from typing import List
import re

from recipe_engine import recipe_api
from recipe_engine import step_data
from recipe_engine.recipe_api import StepFailure

# Packages are relative to chromiumos/infra/, see
# https://chrome-infra-packages.appspot.com/p/chromiumos/infra.
SUPPORTED_PACKAGES = [
    'branch_util',
    'conductor',
    'manifest_doctor',
]

# List of packages for which we should use the new pin (as opposed to falling
# back to the `prod` label), only intended for use during the initial rollout.
# TODO(b/305967772): Remove.
ENABLED_PACKAGES = [
    'branch_util',
    'manifest_doctor',
]


class GobinAPI(recipe_api.RecipeApi):
  """Module for interacting with Go binaries built from infra/infra."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    self._cipd_paths = {}
    self._infra_infra_commit = None

  def _full_package_name(self, package: str) -> str:
    """Return the full package name for a package.

    Example:
      manifest_doctor --> chromiumos/infra/manifest_doctor/linux-amd64
    """
    if package.startswith('chromiumos/infra/'):
      return package
    return f'chromiumos/infra/{package}/${{platform}}'

  def _package_shortname(self, package: str) -> str:
    """Return the short name for a package.

    Example:
      chromiumos/infra/manifest_doctor/linux-amd64 --> manifest_doctor
    """
    if package.startswith('chromiumos/infra/'):
      return package.split('/')[2]
    return package

  @property
  def supported_packages(self):
    """Return the golang packages supported by this module."""
    return [self._full_package_name(package) for package in SUPPORTED_PACKAGES]

  def ensure_package(self, package: str):
    """Ensure that the specified package is installed.

    Looks up the instance associated with the infra/infra commit stored in
    infrainfra-golang.version.
    """
    package_fullname = self._full_package_name(package)
    if package_fullname not in self.supported_packages:
      raise StepFailure(f'unsupported gobin `{package}`')

    if package_fullname in self._cipd_paths:
      return

    package_shortname = self._package_shortname(package)

    with self.m.context(infra_steps=True):
      with self.m.step.nest(f'ensure {package_shortname}') as presentation:
        instance_id = None
        if package_shortname in ENABLED_PACKAGES:
          # Read the infra/infra commit from the gobin pin file.
          if not self._infra_infra_commit:
            self._infra_infra_commit = self.m.file.read_text(
                'read infrainfra golang version',
                self.repo_resource('infra', 'config',
                                   'infrainfra-golang.version'),
                test_data='deadbeef')

          cipd_json_file = self.m.path['cleanup'].join('cipd.json')
          self.m.step('cipd search', [
              'cipd', 'search', package_fullname, '-tag',
              f'git_revision:{self._infra_infra_commit}', '-json-output',
              cipd_json_file
          ])

          cipd_json = self.m.file.read_text(f'read {cipd_json_file}',
                                            cipd_json_file)

          try:
            package_data = json.loads(cipd_json)['result']
            for package_info in package_data:
              if package_info['package'].startswith(
                  re.sub(r'\${platform}$', '', package_fullname)):
                instance_id = package_info['instance_id']
                break
          except json.decoder.JSONDecodeError as e:
            presentation.logs['exception'] = traceback.format_exc()
            raise StepFailure('could not parse JSON') from e
          except KeyError as e:
            presentation.logs['exception'] = traceback.format_exc()
            raise StepFailure('incorrect JSON') from e

          if instance_id is None:
            raise StepFailure(
                f'could not find instance for infra/infra commit {self._infra_infra_commit}'
            )
        else:
          # The package has not yet been migrated to use the pin.
          # TODO(b/305967772): Remove.
          instance_id = 'staging' if self.m.cros_infra_config.is_staging else 'prod'
          presentation.step_text = f'using legacy `{instance_id}` pin'

        cipd_dir = self.m.path['start_dir'].join('cipd')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(package_fullname, instance_id)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cipd_paths[package_fullname] = cipd_dir.join(package)

  def call(self, package: str, cmd: List[str], step_name: str = None,
           **kwargs) -> step_data.StepData:
    """Call a binary with the given args."""
    self.ensure_package(package)
    package_fullname = self._full_package_name(package)

    cmd = [self._cipd_paths[package_fullname]] + cmd

    return self.m.step(step_name or f'run {package}', cmd, **kwargs)
