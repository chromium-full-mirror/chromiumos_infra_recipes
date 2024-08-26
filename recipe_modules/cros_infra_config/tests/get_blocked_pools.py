# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the get_blocked_pools_config function."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
]


def RunSteps(api):
  blocked_pools = api.cros_infra_config.get_blocked_pools_config()

  api.assertions.assertEqual(blocked_pools, ['blockedPool'])


def GenTests(api):
  yield api.test('blocked_pools',
                 api.post_process(post_process.DropExpectation))
