# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS version numbers."""

from PB.recipe_modules.chromeos.cros_version.cros_version import CrosVersionProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_infra_config',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'git_footers',
    'gobin',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CrosVersionProperties
