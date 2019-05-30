# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_history.cros_history import (
    CrosHistoryProperties)

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'recipe_engine/time',
    'naming',
]

PROPERTIES = CrosHistoryProperties
