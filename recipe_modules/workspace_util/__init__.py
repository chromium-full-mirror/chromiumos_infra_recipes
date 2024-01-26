# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the workspace_util module."""

from PB.recipe_modules.chromeos.workspace_util.workspace_util import WorkspaceUtilProperties

DEPS = [
    'cros_build_api',
    'recipe_engine/context',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_relevance',
    'cros_source',
    'easy',
    'src_state',
]


PROPERTIES = WorkspaceUtilProperties
