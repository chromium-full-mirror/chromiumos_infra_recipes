# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/isolated',
    'recipe_engine/path',
    'recipe_engine/python',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'depot_tools/gclient',
    'cros_build_api',
    'portage',
]

from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties

PROPERTIES = ChromeProperties
