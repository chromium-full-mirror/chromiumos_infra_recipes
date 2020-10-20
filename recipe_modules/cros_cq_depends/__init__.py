# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_source',
    'easy',
    'git',
    'repo',
    'support',
]

from PB.recipe_modules.chromeos.cros_cq_depends.cros_cq_depends import (
    CrosCqDependsProperties)

PROPERTIES = CrosCqDependsProperties
