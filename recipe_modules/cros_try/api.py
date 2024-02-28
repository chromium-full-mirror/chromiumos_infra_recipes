# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with `cros try`-initiated jobs."""

from typing import Optional

from recipe_engine.recipe_api import RecipeApi, StepFailure

from PB.recipe_modules.chromeos.cros_try.cros_try import CrosTryProperties


class CrosTryApi(RecipeApi):
  """A module for checking `cros try` builds."""

  def __init__(self, properties: CrosTryProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._properties = properties

  def check_try_version(self):
    """Checks that this specific `cros try` invocation is supported."""
    if not self._properties.enforce_support:
      return
    # crrev.com/c/4205799 updated `cros try` to track a CIPD ref instead of a
    # specific CIPD version, allowing us to push updates to users. We want to
    # invalidate try builds that (roughly) predated this change.
    # This can be removed after it has baked for a sufficiently long period of
    # time (several quarters).
    with self.m.step.nest('check `cros try` version'):
      is_try_build = False
      for tag in self.m.buildbucket.build.tags:
        if tag.key == 'tryjob-launcher':
          is_try_build = True

      if not is_try_build:
        return
      if not self._properties.supported_build:
        raise StepFailure(
            'Using outdated version of `cros try`, please see go/cros-try#stale.'
        )

  def get_invoker(self) -> Optional[str]:
    """Get the email of the tryjob invoker, if any."""
    with self.m.step.nest('get `cros try` invoker'):
      for tag in self.m.buildbucket.build.tags:
        if tag.key == 'tryjob-launcher':
          return tag.value
    return None
