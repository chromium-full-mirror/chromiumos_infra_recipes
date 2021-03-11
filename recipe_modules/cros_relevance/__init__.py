# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_build_api',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_source',
    'easy',
    'repo',
    'src_state',
]

from PB.recipe_modules.chromeos.cros_relevance.cros_relevance import (
    CrosRelevanceProperties)

PROPERTIES = CrosRelevanceProperties
