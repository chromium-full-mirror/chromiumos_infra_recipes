# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_paygen.cros_paygen import (
    CrosPaygenProperties)

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/random',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/gsutil',
    'cros_infra_config',
    'cros_release_util',
    'cros_sdk',
    'cros_source',
    'cros_storage',
    'cros_test_plan',
    'cros_version',
    'metadata',
    'naming',
    'skylab',
    'util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CrosPaygenProperties
