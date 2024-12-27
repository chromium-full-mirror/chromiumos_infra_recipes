# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The `remoteexec` module provides the ability to interact with remote execution services."""

from PB.recipe_modules.chromeos.remoteexec.remoteexec import RemoteexecProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
]


PROPERTIES = RemoteexecProperties
