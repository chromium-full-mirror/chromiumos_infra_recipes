# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deps for cros_artifacts."""

from PB.recipe_modules.chromeos.cros_artifacts.cros_artifacts import CrosArtifactsProperties
from recipe_engine.recipe_api import Property

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/bcid_reporter',
    'recipe_engine/cv',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'code_coverage',
    'cros_build_api',
    'cros_infra_config',
    'cros_snapshot',
    'cros_source',
    'cros_version',
    'disk_usage',
    'dlc_utils',
    'easy',
    'failures',
    'metadata',
]


PROPERTIES = CrosArtifactsProperties
