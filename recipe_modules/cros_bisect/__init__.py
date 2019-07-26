# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/step',
    'easy',
    'failures',
]

from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)

PROPERTIES = CrosBisectProperties
