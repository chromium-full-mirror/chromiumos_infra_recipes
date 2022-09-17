# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'analysis_service',
    'portage',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from PB.recipe_modules.chromeos.cros_build_api.cros_build_api import (
    CrosBuildApiProperties)

PROPERTIES = CrosBuildApiProperties
