# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

# NOTE: when this version is bumped, you MUST bump the `cbuildbot-prod` CIPD
# ref of the skylab CIPD package (chromiumos/infra/skylab/linux-amd64) to the
# latest stable skylab package version.
_MINIMUM_CLI_VERSION = 3


class ServiceVersionCommand(recipe_api.RecipeApi):
  """Module for issuing ServiceVersion commands"""

  def __init__(self, properties, **kwargs):
    super(ServiceVersionCommand, self).__init__(**kwargs)
    self._version = properties.version

  def validate_service_version_if_exists(self):
    """Validate the caller's service version if they sent one."""
    if self._version.crosfleet_tool:
      self._validate_crosfleet_version()
    if self._version.skylab_tool:
      self._validate_skylab_version()

  def _validate_skylab_version(self):
    """Validate that the caller's skylab tool version number is up-to-date by
    comparing it to the minimum accepted CLI version.
    """
    with self.m.step.nest('validate skylab tool version'):
      if self._version.skylab_tool < _MINIMUM_CLI_VERSION:
        raise self.m.step.StepFailure(
            'this build was launched with an outdated version of the skylab '
            'tool; please update via `skylab update` and try again')

  def _validate_crosfleet_version(self):
    """Validate that the caller's crosfleet tool version number is up-to-date by
    comparing it to the minimum accepted CLI version.
    """
    with self.m.step.nest('validate crosfleet tool version'):
      if self._version.crosfleet_tool < _MINIMUM_CLI_VERSION:
        raise self.m.step.StepFailure(
            'this build was launched with an outdated version of the crosfleet '
            'tool; please update via `crosfleet update` and try again')
