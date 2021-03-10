# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

_MINIMUM_SKYLAB_VERSION = 2


class ServiceVersionCommand(recipe_api.RecipeApi):
  """Module for issuing ServiceVersion commands"""

  def __init__(self, properties, **kwargs):
    super(ServiceVersionCommand, self).__init__(**kwargs)
    self._version = properties.version

  def validate_skylab_version(self):
    """Validate that the caller's skylab tool version number is up-to-date.
    """
    with self.m.step.nest('validate Skylab tool version'):
      is_valid = self._version and self._version.skylab_tool >= _MINIMUM_SKYLAB_VERSION
      if not is_valid:
        raise self.m.step.StepFailure(
            'this build was launched with an outdated version of the skylab '
            'tool. Please update via `skylab update` and try again.')
