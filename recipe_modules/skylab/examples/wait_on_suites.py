# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'skylab',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


def RunSteps(api):

  hw_test = api.skylab.test_api.hw_test()
  task = api.skylab.test_api.skylab_task(id=1234, url='https://google.com',
                                         test=hw_test)
  actual = api.skylab.wait_on_suites(task)[0]

  expected = api.skylab.SkylabResult(task=task, success=True, child_results=[])
  api.assertions.assertEqual(actual.task, expected.task)
  api.assertions.assertEqual(actual.success, expected.success)


def GenTests(api):

  yield (api.test('basic') +  #
         api.buildbucket.simulated_collect_output(
             [api.skylab.test_with_multi_response(1234, success=True)],
             step_name='collect skylab tasks v2.buildbucket.collect'))

  yield (api.test('build_without_response') +  #
         api.buildbucket.simulated_collect_output([build_pb2.Build(
             id=1234)], step_name='collect skylab tasks v2.buildbucket.collect')
         + api.expect_exception('AssertionError'))
