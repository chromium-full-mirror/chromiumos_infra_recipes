# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deps and properties for LFG functions."""

from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenProperties

DEPS = {
    'depot_tools_gerrit': 'depot_tools/gerrit',
    'buildbucket': 'recipe_engine/buildbucket',
    'cq': 'recipe_engine/cq',
    'step': 'recipe_engine/step',
    'time': 'recipe_engine/time',
    'buildbucket_stats': 'buildbucket_stats',
    'cros_infra_config': 'cros_infra_config',
    'cros_history': 'cros_history',
    'easy': 'easy',
    'failures': 'failures',
    'gerrit': 'gerrit',
    'git_footers': 'git_footers',
    'greenness': 'greenness',
    'lfg_util': 'lfg_util',
}


PROPERTIES = LooksForGreenProperties
