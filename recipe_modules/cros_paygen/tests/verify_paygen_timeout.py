# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

DEPS = [
    'recipe_engine/assertions',
    'cros_paygen',
]

from recipe_engine import post_process


def RunSteps(api):
  # Test timeout settings (includes individual runs and orch).
  api.assertions.assertEqual(7 * 60 * 60,
                             api.cros_paygen.paygen_orchestrator_timeout_sec)


def GenTests(api):
  yield api.test('basic', api.post_check(post_process.StatusSuccess))
