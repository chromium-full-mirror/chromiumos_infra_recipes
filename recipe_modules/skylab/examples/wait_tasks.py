# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/json',
    'easy',
    'skylab',
]

from PB.test_platform.skylab_tool.result import WaitTasksResult


def RunSteps(api):

  hw_test = api.skylab.test_api.hw_test()
  task = api.skylab.test_api.skylab_task(id=1234, url='https://google.com',
                                         test=hw_test)
  actual = api.skylab.wait_tasks([task])[0]
  expected = api.skylab.SkylabResult(task=task, success=True, child_results=[])
  api.assertions.assertEqual(actual.task, expected.task)
  api.assertions.assertEqual(actual.success, expected.success)
  api.skylab.wait_tasks([task], dev=True)


def GenTests(api):
  yield (api.test('basic') +  #
         api.easy.simulate_json_step('collect skylab tasks.skylab wait-tasks',
                                     api.skylab.wait_tasks_json_output()))

  yield (api.test('bad_output') +  #
         api.step_data('collect skylab tasks.skylab wait-tasks',
                       api.json.output({
                           'bad': 'json'
                       }), retcode=100))
