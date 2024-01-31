# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deps and properties for LFG functions."""

from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/step',
    'recipe_engine/time',
    'buildbucket_stats',
    'cros_infra_config',
    'cros_source',
    'easy',
    'failures',
    'gerrit',
    'git_footers',
    'greenness',
    'lfg_util',
    'src_state',
]


PROPERTIES = LooksForGreenProperties
