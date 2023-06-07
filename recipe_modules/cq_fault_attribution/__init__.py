# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'recipe_engine/time',
    'easy',
    'cros_source',
    'looks_for_green',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'
