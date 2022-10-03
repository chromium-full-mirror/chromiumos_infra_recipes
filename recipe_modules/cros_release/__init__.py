# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_release.cros_release import CrosReleaseProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'build_menu',
    'build_reporting',
    'builder_metadata',
    'cros_artifacts',
    'cros_release_util',
    'cros_test_plan',
    'cros_version',
    'easy',
    'gerrit',
    'git',
    'manifest_doctor',
    'paygen_orchestration',
    'repo',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CrosReleaseProperties
