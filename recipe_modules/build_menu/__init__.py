# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/path',
    'recipe_engine/step',
    'bot_cost',
    'cros_artifacts',
    'cros_bisect',
    'cros_build_api',
    'cros_infra_config',
    'cros_paygen',
    'cros_prebuilts',
    'cros_relevance',
    'cros_sdk',
    'cros_source',
    'cros_tags',
    'cros_version',
    'easy',
    'failures',
    'metadata',
    'metadata_json',
    'src_state',
    'sysroot_util',
    'test_util',
    'workspace_util',
]

from PB.recipe_modules.chromeos.build_menu.build_menu import BuildMenuProperties

PROPERTIES = BuildMenuProperties
