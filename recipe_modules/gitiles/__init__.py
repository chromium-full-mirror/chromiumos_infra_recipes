# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the gitiles module."""

DEPS = [
    'recipe_engine/path',
    'recipe_engine/json',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'easy',
    'support',
]

from .api import GitilesApi as API
from .test_api import GitilesTestApi as TEST_API
