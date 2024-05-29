# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the cros_snapshot module."""

from PB.recipe_modules.chromeos.cros_snapshot.cros_snapshot import CrosSnapshotProperties

DEPS = [
    'recipe_engine/step',
    'recipe_engine/context',
    'cros_infra_config',
    'src_state',
    'git_footers',
]

PROPERTIES = CrosSnapshotProperties
