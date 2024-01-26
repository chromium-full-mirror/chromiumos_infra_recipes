# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the labpack module."""

import PB.recipe_modules.chromeos.labpack.labpack as labpackpb

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/step',
    'cros_tags',
]


PROPERTIES = labpackpb.LabpackProperties
