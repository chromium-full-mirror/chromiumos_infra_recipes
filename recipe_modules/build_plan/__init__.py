# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'cros_infra_config',
    'cros_history',
    'cros_relevance',
    'cros_tags',
    'looks_for_green',
    'easy',
    'git_footers',
    'test_util',
]

from PB.recipe_modules.chromeos.build_plan.build_plan import BuildPlanProperties

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = BuildPlanProperties
