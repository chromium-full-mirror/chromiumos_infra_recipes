# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.checkpoint.checkpoint import CheckpointProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'easy',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CheckpointProperties
