# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_sdk.cros_sdk import CrosSdkProperties

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'cros_build_api',
    'cros_infra_config',
    'cros_relevance',
    'cros_source',
    'easy',
    'git',
    'goma',
    'overlayfs',
    'remoteexec',
    'src_state',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = CrosSdkProperties
