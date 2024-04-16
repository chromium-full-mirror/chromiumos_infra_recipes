# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS version numbers."""

from PB.recipe_modules.chromeos.cros_version.cros_version import CrosVersionProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'git_footers',
    'gobin',
    'src_state',
]


PROPERTIES = CrosVersionProperties
