# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_release_config.cros_release_config import CrosReleaseConfigProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/step',
    'build_menu',
    'cros_artifacts',
    'cros_schedule',
    'cros_source',
    'cros_version',
    'gerrit',
    'git',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = CrosReleaseConfigProperties
