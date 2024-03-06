# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Init for incremental module."""

# pylint: disable=import-error
from PB.recipe_modules.chromeos.incremental.incremental import IncrementalProperties

DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'build_menu',
    'cros_sdk',
    'cros_source',
    'git',
    'repo',
]


PROPERTIES = IncrementalProperties
