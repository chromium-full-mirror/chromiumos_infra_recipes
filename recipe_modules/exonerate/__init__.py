# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties

DEPS = [
    'depot_tools/gitiles',
    'recipe_engine/step',
    'cros_infra_config',
    'easy',
    'naming',
    'skylab',
    'urls',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = ExonerateProperties
