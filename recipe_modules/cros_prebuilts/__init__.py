# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_prebuilts.cros_prebuilts import (
    CrosPrebuiltsProperties)

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'cros_build_api',
    'cros_infra_config',
    'cros_source',
    'cros_version',
    'git',
    'git_footers',
    'git_txn',
    'repo',
    'src_state',
]

PROPERTIES = CrosPrebuiltsProperties
