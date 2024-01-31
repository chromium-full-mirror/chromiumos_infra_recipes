# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/json',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'cros_infra_config',
    'cros_history',
    'cros_source',
    'cros_tags',
    'easy',
    'git_footers',
    'greenness',
    'metadata',
    'skylab_results',
    'src_state',
]


PROPERTIES = SkylabProperties
