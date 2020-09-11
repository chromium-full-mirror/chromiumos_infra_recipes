# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

from PB.recipe_modules.chromeos.cros_paygen.cros_paygen import CrosPaygenProperties

PROPERTIES = CrosPaygenProperties
