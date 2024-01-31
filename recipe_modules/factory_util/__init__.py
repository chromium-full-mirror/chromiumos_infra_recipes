# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module for util functions associated with factory builds."""

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'build_menu',
    'cros_artifacts',
    'cros_source',
    'cros_version',
]

