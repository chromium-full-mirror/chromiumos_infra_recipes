# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
DEPS = [
    'recipe_engine/cipd', 'recipe_engine/context', 'recipe_engine/path',
    'recipe_engine/step', 'depot_tools/depot_tools', 'cros_version'
]

from PB.recipe_modules.chromeos.cros_branch.cros_branch import (
    CrosBranchProperties)

PROPERTIES = CrosBranchProperties
