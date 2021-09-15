# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'cros_infra_config',
    'cros_tags',
    'easy',
    'src_state',
]

PROPERTIES = SkylabProperties
