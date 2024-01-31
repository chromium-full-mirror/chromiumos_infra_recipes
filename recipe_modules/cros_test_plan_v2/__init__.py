# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for end-to-end test planning."""

from PB.recipe_modules.chromeos.cros_test_plan_v2.cros_test_plan_v2 import CrosTestPlanV2Properties

DEPS = [
    'infra/docker',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_build_api',
    'cros_infra_config',
    'cros_test_plan',
    'easy',
    'failures',
    'gerrit',
    'gobin',
    'src_state',
    'depot_tools/gitiles',
]


PROPERTIES = CrosTestPlanV2Properties
