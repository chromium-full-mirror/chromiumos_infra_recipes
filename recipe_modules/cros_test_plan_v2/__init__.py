# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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
    'gerrit',
    'gitiles',
]

from PB.recipe_modules.chromeos.cros_test_plan_v2.cros_test_plan_v2 import (
    CrosTestPlanV2Properties)

PROPERTIES = CrosTestPlanV2Properties
