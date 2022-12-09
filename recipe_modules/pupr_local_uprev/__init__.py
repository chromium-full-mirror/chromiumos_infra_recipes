# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'gerrit',
    'git',
    'naming',
    'repo',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'
