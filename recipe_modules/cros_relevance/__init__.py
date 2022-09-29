# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_relevance.cros_relevance import CrosRelevanceProperties

DEPS = [
    'cros_build_api',
    'recipe_engine/cipd',
    'recipe_engine/cq',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_history',
    'cros_infra_config',
    'cros_source',
    'easy',
    'git_footers',
    'repo',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = CrosRelevanceProperties
