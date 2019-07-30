# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'skylab',
]


def RunSteps(api):

  hw_test = api.skylab.test_api.hw_test()
  task = api.skylab.test_api.skylab_task(id='ID', url='https://google.com',
                                         test=hw_test)
  actual = api.skylab.wait_tasks([task])
  expected = [api.skylab.SkylabResult(task=task, success=True, output=None)]
  api.assertions.assertEqual(actual, expected)


def GenTests(api):
  yield api.test('basic')
