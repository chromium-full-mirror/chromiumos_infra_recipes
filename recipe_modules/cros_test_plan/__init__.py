# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_source',
    'git',
    'repo',
]

from PB.recipe_modules.chromeos.cros_test_plan.cros_test_plan import (
    CrosTestPlanProperties)

PROPERTIES = CrosTestPlanProperties
