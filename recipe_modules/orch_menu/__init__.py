# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for orchestrator steps"""

from PB.recipe_modules.chromeos.orch_menu.orch_menu import OrchMenuProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cv',
    'recipe_engine/futures',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'bot_cost',
    'build_menu',
    'build_plan',
    'checkpoint',
    'conductor',
    'cros_artifacts',
    'cros_cq_additional_tests',
    'cros_history',
    'cros_infra_config',
    'cros_lkgm',
    'cros_release',
    # TODO(b/316010599): Remove after experiment concludes.
    'cros_relevance',
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
    'gobin',
    'greenness',
    'looks_for_green',
    'metadata',
    'naming',
    'skylab',
    'skylab_results',
    'src_state',
    'test_util',
    'workspace_util',
]


PROPERTIES = OrchMenuProperties
