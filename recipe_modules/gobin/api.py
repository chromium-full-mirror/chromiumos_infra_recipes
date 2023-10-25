# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with Go binaries built from infra/infra."""

import json
import traceback
from typing import List, Optional
import re

from recipe_engine import recipe_api
from recipe_engine import step_data
from recipe_engine.recipe_api import StepFailure

# Packages are relative to chromiumos/infra/, see
# https://chrome-infra-packages.appspot.com/p/chromiumos/infra.
SUPPORTED_PACKAGES = [
    'branch_util',
    'build_plan_generator',
    'build_poller',
    'conductor',
    'manifest_doctor',
    'pointless_build_checker',
    'test_plan',
    'test_plan_generator',
    'upload_debug_symbols',
    'version_bumper',
    # For testing only.
    'my_gobin',
]

# List of packages for which we should use the new pin (as opposed to falling
# back to the `prod` label), only intended for use during the initial rollout.
# TODO(b/305967772): Remove.
ENABLED_PACKAGES = [
    # For testing only.
    'my_gobin',
]

CIPD_TEST_JSON = '''{
    "result": [
        {
            "package": "%s",
            "instance_id": "wzCA5zCcIkg0uYroNN91fpH1oQLMVHYaXM8RS9SuQwUC"
        }
    ]
}
'''


class GobinAPI(recipe_api.RecipeApi):
  """Module for interacting with Go binaries built from infra/infra."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    self._cipd_paths = {}
    self._infra_infra_commit = None

  def _package_fullname(self, package: str) -> str:
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
    return [self._package_fullname(package) for package in SUPPORTED_PACKAGES]

  def _get_instance_for_sha(self, package_fullname: str,
                            sha: str) -> Optional[str]:
    """Find the associated CIPD instance for the given package for the given infra/infra commit."""
    package_shortname = self._package_shortname(package_fullname)
    with self.m.step.nest(
        f'find cipd instance for {package_shortname} for infra/infra commit {sha}'
    ) as presentation:
      cipd_json_file = self.m.path['cleanup'].join('cipd.json')
      self.m.step('cipd search', [
          'cipd', 'search', package_fullname, '-tag', f'git_revision:{sha}',
          '-json-output', cipd_json_file
      ])

      cipd_json = self.m.file.read_text(f'read {cipd_json_file}',
                                        cipd_json_file)

      try:
        package_data = json.loads(cipd_json)['result']
        for package_info in package_data:
          if package_info['package'].startswith(
              re.sub(r'\${platform}$', '', package_fullname)):
            package_fullname_with_platform = package_info['package']
            instance_id = package_info['instance_id']
            presentation.logs[
                'cipd instance'] = f'https://chrome-infra-packages.appspot.com/p/{package_fullname_with_platform}/+/{instance_id}'
            return instance_id
      except json.decoder.JSONDecodeError as e:
        presentation.logs['exception'] = traceback.format_exc()
        raise StepFailure('could not parse JSON') from e
      except KeyError as e:
        presentation.logs['exception'] = traceback.format_exc()
        raise StepFailure('incorrect JSON') from e

      return None

  def _is_valid_sha(self, sha: str) -> bool:
    """Check if there exists a CIPD instance for each supported package for the given infra/infra commit."""
    for package in SUPPORTED_PACKAGES:
      package_fullname = self._package_fullname(package)
      if self._get_instance_for_sha(package_fullname, sha) is None:
        return False
    return True

  def get_latest_pin_value(self, current_pin: str) -> str:
    """Returns the most recent infra/infra SHA that is a viable pin.

    Specifically, returns the latest SHA for which there is a CIPD instance for
    each of SUPPORTED_PACKAGES.
    """

    infra_infra_checkout = self.m.path.mkdtemp()
    with self.m.context(cwd=infra_infra_checkout):
      self.m.git.clone('https://chromium.googlesource.com/infra/infra/',
                       branch='main')
      self.m.git.fetch_ref('https://chromium.googlesource.com/infra/infra/',
                           current_pin)

      res = self.m.step(
          f'get commits since {current_pin}',
          ['git', 'rev-list', '--ancestry-path', f'{current_pin}~..HEAD'],
          stdout=self.m.raw_io.output_text(add_output_log=True))
      commits = res.stdout.strip()
      if not commits:
        raise StepFailure(f'could not find {current_pin} in the `main` branch')
      # Remove the current_pin from the end of the list, we queried from its
      # parent so we can distinguish between no-changes and not-in-main.
      commits = commits.split('\n')[:-1]

      # Commits are ordered newest to oldest.
      # TODO(b/305967772): Optimize, use binary search or something.
      for commit in commits:
        if self._is_valid_sha(commit):
          return commit
      # If none of the commits are valid, just return the current pin.
      return current_pin

  def ensure_package(self, package: str):
    """Ensure that the specified package is installed.

    Looks up the instance associated with the infra/infra commit stored in
    infrainfra-golang.version.
    """
    package_fullname = self._package_fullname(package)
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

          instance_id = self._get_instance_for_sha(package_fullname,
                                                   self._infra_infra_commit)

          if instance_id is None:
            raise StepFailure(
                f'could not find instance for infra/infra commit {self._infra_infra_commit}'
            )
        else:
          # The package has not yet been migrated to use the pin.
          # TODO(b/305967772): Remove.
          instance_id = 'staging' if self.m.cros_infra_config.is_staging else 'prod'
          presentation.step_text = f'using legacy `{instance_id}` pin'

        cipd_dir = self.m.path['start_dir'].join(f'cipd/{package_shortname}')
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(package_fullname, instance_id)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cipd_paths[package_fullname] = cipd_dir.join(package)

  def call(self, package: str, cmd: List[str], step_name: str = None,
           **kwargs) -> step_data.StepData:
    """Call a binary with the given args."""
    self.ensure_package(package)
    package_fullname = self._package_fullname(package)

    cmd = [self._cipd_paths[package_fullname]] + cmd

    return self.m.step(step_name or f'run {package}', cmd, **kwargs)
