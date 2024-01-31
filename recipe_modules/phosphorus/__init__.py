# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.phosphorus.phosphorus import \
  PhosphorusProperties
from PB.recipe_modules.chromeos.phosphorus.phosphorus import \
  PhosphorusEnvProperties

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'easy',
]


PROPERTIES = PhosphorusProperties
ENV_PROPERTIES = PhosphorusEnvProperties
