# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner import \
  CrosToolRunnerProperties
from PB.recipe_modules.chromeos.cros_tool_runner.cros_tool_runner import \
  CrosToolRunnerEnvProperties

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'easy',
]


PROPERTIES = CrosToolRunnerProperties
ENV_PROPERTIES = CrosToolRunnerEnvProperties
