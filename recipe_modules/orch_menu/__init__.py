# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'bot_cost',
    'build_menu',
    'build_plan',
    'cros_artifacts',
    'cros_bisect',
    'cros_history',
    'cros_infra_config',
    'cros_release',
    'cros_resultdb',
    'cros_source',
    'cros_tags',
    'cros_test_plan',
    'cros_test_plan_v2',
    'cros_test_proctor',
    'cros_version',
    'easy',
    'failures',
    'gerrit',
    'git',
    'git_footers',
    'gitiles',
    'greenness',
    'naming',
    'metadata',
    'skylab',
    'src_state',
    'test_util',
    'workspace_util',
]

from PB.recipe_modules.chromeos.orch_menu.orch_menu import OrchMenuProperties

PYTHON_VERSION_COMPATIBILITY = 'PY2'

PROPERTIES = OrchMenuProperties
