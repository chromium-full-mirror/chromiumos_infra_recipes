# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_som',
    'naming',
    'urls',
]

from PB.recipe_modules.chromeos.failures.failures import FailuresProperties

PROPERTIES = FailuresProperties