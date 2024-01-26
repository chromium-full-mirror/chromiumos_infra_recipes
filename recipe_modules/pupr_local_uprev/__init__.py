# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the pupr_local_uprev module."""

from PB.recipe_modules.chromeos.pupr_local_uprev.pupr_local_uprev import (
    PuprLocalUprevProperties)

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_build_api',
    'cros_source',
    'cros_sdk',
    'gerrit',
    'git',
    'naming',
    'repo',
    'src_state',
]


PROPERTIES = PuprLocalUprevProperties
