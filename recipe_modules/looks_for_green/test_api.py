# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test util function for looks_for_green."""

from typing import Callable, Dict

from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStatus

from recipe_engine.post_process_inputs import Step
from recipe_engine import post_process


def LooksStatusEquals(check: Callable[[str, bool], bool],
                      step_odict: Dict[str, Step], value: LooksForGreenStatus):
  """Assert that the status matches."""
  build_properties = post_process.GetBuildProperties(step_odict)
  check(build_properties['looks_for_green'].get(
      'status', LooksForGreenStatus.STATUS_UNSPECIFIED) ==
        LooksForGreenStatus.Name(value))
