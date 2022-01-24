# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'git_footers',
    'src_state',
]

from PB.recipe_modules.chromeos.cros_version.cros_version import (
    CrosVersionProperties)

PROPERTIES = CrosVersionProperties
