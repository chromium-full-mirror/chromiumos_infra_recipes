# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine.config import Single

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'recipe_engine/time',
]

PROPERTIES = {
    # Number of seconds to look back for passed builds.
    'lookback_no_of_seconds':
        Property(kind=Single((float, int)), default=5 * 24 * 60 * 60)
}
