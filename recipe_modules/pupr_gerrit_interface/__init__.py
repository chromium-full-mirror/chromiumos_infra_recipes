# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to interface with Gerrit for PUpr (Parallel Uprevs)."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_cq_depends',
    'cros_infra_config',
    'cros_source',
    'easy',
    'gerrit',
    'git_cl',
    'git_footers',
    'pupr',
    'pupr_local_uprev',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'
