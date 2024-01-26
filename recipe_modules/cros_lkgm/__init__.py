# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the cros_lkgm module."""

from PB.recipe_modules.chromeos.cros_lkgm.cros_lkgm import (CrosLkgmProperties)

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_release',
    'cros_schedule',
    'cros_source',
    'cros_version',
]


PROPERTIES = CrosLkgmProperties
