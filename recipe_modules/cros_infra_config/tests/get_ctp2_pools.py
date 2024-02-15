# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the get_ctp2_pools_config function."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
]


def RunSteps(api):
  ctp2_pools = api.cros_infra_config.get_ctp2_pools_config()

  api.assertions.assertEqual(ctp2_pools, ['schedukeTest', 'examplePool'])


def GenTests(api):
  yield api.test('ctp2_pools', api.post_process(post_process.DropExpectation))
