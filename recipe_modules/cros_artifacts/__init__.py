# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/led',
    'recipe_engine/path',
    'recipe_engine/step',
    'code_coverage',
    'cros_build_api',
    'cros_infra_config',
    'cros_source',
    'cros_version',
    'disk_usage',
    'easy',
    'metadata',
]

from PB.recipe_modules.chromeos.cros_artifacts.cros_artifacts import CrosArtifactsProperties

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = CrosArtifactsProperties
