# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the chrome module."""

from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties

DEPS = [
    'recipe_engine/cas',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/depot_tools',
    'depot_tools/gclient',
    'cros_build_api',
    'cros_sdk',
    'easy',
    'gerrit',
    'git_footers',
    'future_utils',
    'workspace_util',
]


PROPERTIES = ChromeProperties
