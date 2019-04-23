# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_build_api',
    'cros_version',
]

PROPERTIES = {
    # Google Storage bucket to upload artifacts to.
    'artifacts_gs_bucket':
        Property(kind=str, default='gs://chromeos-image-archive')
}
