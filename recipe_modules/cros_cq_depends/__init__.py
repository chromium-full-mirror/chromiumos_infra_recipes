# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the cros_cq_depends module."""

from PB.recipe_modules.chromeos.cros_cq_depends.cros_cq_depends import CrosCqDependsProperties

DEPS = [
    'recipe_engine/context',
    'recipe_engine/step',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'repo',
]


PROPERTIES = CrosCqDependsProperties
