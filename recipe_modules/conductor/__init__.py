# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API wrapping the conductor tool."""

from PB.recipe_modules.chromeos.conductor.conductor import ConductorProperties

DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'easy',
    'gobin',
]


PROPERTIES = ConductorProperties
