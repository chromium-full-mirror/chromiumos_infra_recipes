# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import PB.recipe_modules.chromeos.labpack.labpack as labpackpb

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/step',
    'recipe_engine/path',
    'cros_tags',
    'easy',
]


PROPERTIES = labpackpb.LabpackProperties
