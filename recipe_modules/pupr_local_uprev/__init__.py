# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the pupr_local_uprev module."""

from PB.recipe_modules.chromeos.pupr_local_uprev.pupr_local_uprev import (
    PuprLocalUprevProperties)
from .api import PuprLocalUprevApi as API
from .test_api import PuprLocalUprevTestApi as TEST_API

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
    'git_footers',
    'naming',
    'pupr',
    'repo',
    'src_state',
]


PROPERTIES = PuprLocalUprevProperties
