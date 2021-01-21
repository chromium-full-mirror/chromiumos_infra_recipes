# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'build_menu',
    'cros_artifacts',
    'cros_paygen',
    'cros_version',
]

from PB.recipe_modules.chromeos.cros_release.cros_release import (
    CrosReleaseProperties)

PROPERTIES = CrosReleaseProperties
