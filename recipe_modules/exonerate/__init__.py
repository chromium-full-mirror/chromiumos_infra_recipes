# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties

DEPS = [
    'recipe_engine/step',
    'cros_infra_config',
    'naming',
    'skylab',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = ExonerateProperties
