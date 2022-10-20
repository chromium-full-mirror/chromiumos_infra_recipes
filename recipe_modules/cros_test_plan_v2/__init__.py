# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_test_plan_v2.cros_test_plan_v2 import CrosTestPlanV2Properties

DEPS = [
    'infra/docker',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_build_api',
    'cros_infra_config',
    'cros_test_plan',
    'easy',
    'gerrit',
    'gitiles',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CrosTestPlanV2Properties
