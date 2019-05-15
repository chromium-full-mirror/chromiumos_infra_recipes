# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/swarming',
    'skylab',
]


def RunSteps(api):
  task = api.skylab.test_api.skylab_task()

  actual = api.skylab.wait_suites([task])
  expected = [
      api.skylab.test_api.skylab_result(task=task, success=True,
                                        output='hello world!')
  ]

  api.assertions.assertEqual(actual, expected)


def GenTests(api):
  yield api.test('basic')
