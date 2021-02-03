# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/properties',
    'depot_tools/depot_tools',
    'depot_tools/gitiles',
    'cros_infra_config',
    'test_util',
    'easy',
    'git',
    'failures',
    'src_state',
]

from PB.recipe_modules.chromeos.repo.repo import (RepoProperties)

PROPERTIES = RepoProperties
