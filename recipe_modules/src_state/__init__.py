# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.src_state.src_state import SrcStateProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]


# This module is intended to be something that any of our modules can depend on
# without causing circular dependencies.  As such, it must only depend on
# modules that we have declared as dependencies in infra/config/recipes.cfg.
# All of those have a '/' in the name.
assert [x for x in DEPS if '/' not in x] == [], \
    'src_state depends on CrOS modules'

PROPERTIES = SrcStateProperties
