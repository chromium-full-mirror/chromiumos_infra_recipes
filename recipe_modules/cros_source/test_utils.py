# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Callable, Dict

from PB.recipe_modules.chromeos.cros_source.cros_source import GitStrategy

from recipe_engine.post_process_inputs import Step
from recipe_engine import post_process


def GitStrategyEquals(check: Callable[[str, bool], bool],
                      step_odict: Dict[str, Step], expected_value: GitStrategy):
  """Assert that the git_strategy property is set correctly."""
  build_properties = post_process.GetBuildProperties(step_odict)
  check(
      build_properties.get('cros_source_git_strategy', GitStrategy.UNSPECIFIED)
      == expected_value)
