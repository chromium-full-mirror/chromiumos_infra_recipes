# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_signing.cros_signing import (
    CrosSigningProperties)

DEPS = [
    'cros_build_api',
    'depot_tools/gsutil',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
]

PROPERTIES = CrosSigningProperties
