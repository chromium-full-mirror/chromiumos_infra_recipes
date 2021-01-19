# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'bot_cost',
    'code_coverage',
    'cros_artifacts',
    'cros_bisect',
    'cros_build_api',
    'cros_infra_config',
    'cros_paygen',
    'cros_prebuilts',
    'cros_relevance',
    'cros_sdk',
    'cros_version',
    'easy',
    'failures',
    'metadata_json',
    'sysroot_util',
    'test_util',
    'workspace_util',
]

from PB.recipe_modules.chromeos.build_menu.build_menu import BuildMenuProperties

PROPERTIES = BuildMenuProperties

# TODO(crbug/1099259): Migrate the common build_target properties to the
# module, and stop looking at the global properties.
from PB.recipes.chromeos.build_target import BuildTargetProperties

GLOBAL_PROPERTIES = BuildTargetProperties
