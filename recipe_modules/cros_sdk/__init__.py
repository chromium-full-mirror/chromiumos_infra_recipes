# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Dependencies and properties for the cros_sdk module."""

from PB.recipe_modules.chromeos.cros_sdk.cros_sdk import CrosSdkProperties

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'cros_build_api',
    'cros_infra_config',
    'cros_relevance',
    'cros_source',
    'cros_version',
    'easy',
    'failures',
    'git',
    'goma',
    'overlayfs',
    'remoteexec',
    'src_state',
    'workspace_util',
]


PROPERTIES = CrosSdkProperties
