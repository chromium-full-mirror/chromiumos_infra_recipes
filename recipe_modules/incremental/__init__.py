# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Init for incremental module."""

# pylint: disable=import-error
from PB.recipe_modules.chromeos.incremental.incremental import IncrementalProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'build_menu',
    'cros_sdk',
    'easy',
    'git',
    'repo',
]


PROPERTIES = IncrementalProperties
