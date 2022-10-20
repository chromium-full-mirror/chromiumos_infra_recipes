# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.urls.urls import UrlsProperties

DEPS = [
    'recipe_engine/buildbucket',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = UrlsProperties
