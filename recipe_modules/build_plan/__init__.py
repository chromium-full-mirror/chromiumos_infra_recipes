# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deps and properties for build planning functions."""

from PB.recipe_modules.chromeos.build_plan.build_plan import BuildPlanProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/led',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'chrome',
    'cros_infra_config',
    'cros_history',
    'cros_relevance',
    'cros_source',
    'cros_tags',
    'looks_for_green',
    'easy',
    'failures',
    'gerrit',
    'git',
    'git_footers',
    'future_utils',
    'repo',
    'src_state',
    'test_util',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildPlanProperties
