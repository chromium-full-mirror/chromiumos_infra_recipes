# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test that we can get bot demand."""

DEPS = [
    'recipe_engine/assertions',
    'buildbucket_stats',
]



def RunSteps(api):
  demand = api.buildbucket_stats.get_bot_demand({
      'STARTED': 47,
      'SCHEDULED': 53,
  })
  api.assertions.assertEqual(demand, 100)


def GenTests(api):
  yield api.test('basic')
