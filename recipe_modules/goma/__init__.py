# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'support',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from PB.recipe_modules.chromeos.goma.goma import GomaProperties

PROPERTIES = GomaProperties
