# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with Go binaries built from infra/infra."""

DEPS = [
    'depot_tools/depot_tools',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_version',
    'git',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'
