# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module providing helpers for signing functionality."""

DEPS = [
    'recipe_engine/file',
    'depot_tools/gsutil',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'build_menu',
    'cros_release_util',
    'cros_version',
]
