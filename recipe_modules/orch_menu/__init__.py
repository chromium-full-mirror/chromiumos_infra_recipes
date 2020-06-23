# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/time',
    'bot_cost',
    'build_plan',
    'cros_bisect',
    'cros_history',
    'cros_infra_config',
    'cros_source',
    'cros_tags',
    'cros_test_proctor',
    'failures',
    'gerrit',
    'git',
    'git_footers',
    'gitiles',
    'naming',
    'skylab',
    'test_util',
]

from PB.recipe_modules.chromeos.orch_menu.orch_menu import OrchMenuProperties

PROPERTIES = OrchMenuProperties

# TODO(crbug/1093916): Migrate the common orchestrator properties to the
# module, and stop looking at the global properties.
from PB.recipes.chromeos.orchestrator import OrchestratorProperties

GLOBAL_PROPERTIES = OrchestratorProperties
