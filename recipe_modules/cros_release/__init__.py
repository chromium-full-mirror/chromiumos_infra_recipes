# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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
    'cros_paygen',
    'cros_release_util',
    'cros_test_plan',
    'cros_version',
    'gerrit',
    'git',
    'manifest_doctor',
    'repo',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from PB.recipe_modules.chromeos.cros_release.cros_release import (
    CrosReleaseProperties)

PROPERTIES = CrosReleaseProperties
