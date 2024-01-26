# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the cros_test_runner module."""

from PB.recipe_modules.chromeos.cros_test_runner.cros_test_runner import \
    CrosTestRunnerModuleProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
]


PROPERTIES = CrosTestRunnerModuleProperties
