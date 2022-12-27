# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.signing.signing import (SigningProperties)

DEPS = [
    'cros_build_api',
    'depot_tools/gsutil',
    'easy',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = SigningProperties
