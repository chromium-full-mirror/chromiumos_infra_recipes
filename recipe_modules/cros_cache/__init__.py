# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/file',
    'recipe_engine/path',
    'easy',
]

from .api import CrosCacheApi as API
from .test_api import CrosCacheTestApi as TEST_API
