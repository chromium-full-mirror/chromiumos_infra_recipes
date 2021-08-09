# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_relevance',
    'cros_source',
    'easy',
    'gerrit',
    'repo',
    'src_state',
]

from PB.recipe_modules.chromeos.workspace_util.workspace_util import (
    WorkspaceUtilProperties)

PROPERTIES = WorkspaceUtilProperties
