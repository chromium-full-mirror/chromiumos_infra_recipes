# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the paygen_orchestration module."""

from PB.recipe_modules.chromeos.paygen_orchestration.paygen_orchestration import PaygenOrchestrationProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/led',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/gsutil',
    'conductor',
    'cros_infra_config',
    'cros_sdk',
    'cros_storage',
    'cros_version',
    'naming',
]


PROPERTIES = PaygenOrchestrationProperties
