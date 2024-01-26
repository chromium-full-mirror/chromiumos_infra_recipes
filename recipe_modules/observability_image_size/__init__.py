# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deps and properties for observability-image-size functions."""

from PB.recipe_modules.chromeos.observability_image_size.observability_image_size import ObservabilityImageSizeProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cloud_pubsub',
    'cros_build_api',
    'cros_version',
    'easy',
    'src_state',
]


PROPERTIES = ObservabilityImageSizeProperties
