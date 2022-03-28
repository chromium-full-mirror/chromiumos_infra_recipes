# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_test_runner.cros_test_runner import \
    CrosTestRunnerModuleProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = CrosTestRunnerModuleProperties
