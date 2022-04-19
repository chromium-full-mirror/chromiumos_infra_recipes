# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = {
    'buildbucket': 'recipe_engine/buildbucket',
    'cipd': 'recipe_engine/cipd',
    'context': 'recipe_engine/context',
    'properties': 'recipe_engine/properties',
    'step': 'recipe_engine/step',
    'url': 'recipe_engine/url',
    'depot_gitiles': 'depot_tools/gitiles',

    # Our modules.
    'easy': 'easy',
    'gitiles': 'gitiles',
    'src_state': 'src_state',
    'util': 'util',
}

from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = CrosInfraConfigProperties
