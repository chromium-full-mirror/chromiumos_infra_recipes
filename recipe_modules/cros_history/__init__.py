# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_history.cros_history import (
    CrosHistoryProperties)

DEPS = [
    'depot_tools/gitiles',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/step',
    'recipe_engine/time',
    'cros_tags',
    'easy',
    'exonerate',
    'naming',
    'skylab_results',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CrosHistoryProperties
