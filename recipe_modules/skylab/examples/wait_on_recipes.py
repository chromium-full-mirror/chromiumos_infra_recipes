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
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.taskstate import TaskState
from google.protobuf import duration_pb2

def RunSteps(api):
  hw_test = api.skylab.test_api.hw_test()
  task = api.skylab.test_api.skylab_task(id=1234, url='https://google.com',
                                         test=hw_test)
  actual = api.skylab.wait_on_recipes(
      [task], timeout=duration_pb2.Duration(seconds=3600))[0]

def GenTests(api):

  yield api.test(
      'basic',
      api.buildbucket.simulated_collect_output([
          api.skylab.test_with_execute_response_json(
              1234, TaskState(verdict=TaskState.VERDICT_PASSED))
      ], step_name='collect skylab tasks.buildbucket.collect'),
  )

  yield api.test(
      'infra_failure',
      api.buildbucket.simulated_collect_output([
          api.skylab.test_with_execute_response_json(
              1234, TaskState(life_cycle=TaskState.LIFE_CYCLE_PENDING))
      ], step_name='collect skylab tasks.buildbucket.collect'),
  )

  yield api.test(
      'build_without_response',
      api.buildbucket.simulated_collect_output([build_pb2.Build(
          id=1234)], step_name='collect skylab tasks.buildbucket.collect'),
  )
