# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import CrosInfraConfigProperties

DEPS = {
    'buildbucket': 'recipe_engine/buildbucket',
    'cipd': 'recipe_engine/cipd',
    'context': 'recipe_engine/context',
    'led': 'recipe_engine/led',
    'properties': 'recipe_engine/properties',
    'step': 'recipe_engine/step',
    'time': 'recipe_engine/time',
    'url': 'recipe_engine/url',
    'depot_gitiles': 'depot_tools/gitiles',

    # Our modules.
    'easy': 'easy',
    'gitiles': 'gitiles',
    'src_state': 'src_state',
    'util': 'util',
}


PROPERTIES = CrosInfraConfigProperties
