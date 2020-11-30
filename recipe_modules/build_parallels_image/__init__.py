# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.build_parallels_image.build_parallels_image \
  import BuildParallelsImageEnvProperties

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

ENV_PROPERTIES = BuildParallelsImageEnvProperties
