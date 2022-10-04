# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import CrosBisectProperties

DEPS = [
    'recipe_engine/step',
    'easy',
    'failures',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = CrosBisectProperties
