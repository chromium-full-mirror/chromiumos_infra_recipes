# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/archive',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/isolated',
    'recipe_engine/path',
    'recipe_engine/step',
    'depot_tools/gitiles',
    'cros_infra_config',
    'easy',
    'git',
    'overlayfs',
    'repo',
]

from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties)

PROPERTIES = CrosSourceProperties
