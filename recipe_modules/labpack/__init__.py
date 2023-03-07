# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import PB.recipe_modules.chromeos.labpack.labpack as labpackpb

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/step',
    'recipe_engine/path',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = labpackpb.LabpackProperties
