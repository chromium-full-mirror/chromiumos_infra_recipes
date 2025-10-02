# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/step',
    'recipe_engine/time',
    'easy',
]

from .api import CrosScheduleApi as API
from .test_api import CrosScheduleTestApi as TEST_API
