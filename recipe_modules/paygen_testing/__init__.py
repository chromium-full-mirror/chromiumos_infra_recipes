# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with Paygen. Used by paygen.py."""

DEPS = [
    'recipe_engine/raw_io',
    'depot_tools/gsutil',
    'cros_release_util',
]

from .api import PaygenTestingApi as API
from .test_api import PaygenTestingTestApi as TEST_API
