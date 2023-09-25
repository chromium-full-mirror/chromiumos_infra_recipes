# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.signing.signing import (SigningProperties)

DEPS = [
    'depot_tools/gitiles',
    'depot_tools/gsutil',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cros_build_api',
    'cros_infra_config',
    'cros_version',
    'easy',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = SigningProperties
