# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_try.cros_try import CrosTryProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
]


PROPERTIES = CrosTryProperties
