# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.greenness.greenness import GreennessProperties

DEPS = [
    'recipe_engine/step',
    'cros_infra_config',
    'cros_tags',
    'easy',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = GreennessProperties
