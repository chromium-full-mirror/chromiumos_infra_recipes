# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.workspace_util.workspace_util import WorkspaceUtilProperties

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

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = WorkspaceUtilProperties
