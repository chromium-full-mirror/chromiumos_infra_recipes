# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Basic tests for the urls recipe module."""

import json
from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'skylab',
    'urls',
]

def RunSteps(api):
  build = build_pb2.Build(id=123)
  api.assertions.assertEqual(
      api.urls.get_build_link_map(build),
      {'build page': api.buildbucket.build_url(build_id=123)})

  build = build_pb2.Build(id=123)
  api.assertions.assertEqual(
      api.urls.get_vm_test_link_map(build),
      {'test page': api.buildbucket.build_url(build_id=123)})

  skylab_task = api.skylab.test_api.skylab_task(url='skylab.whatever')
  api.assertions.assertEqual(api.urls.get_skylab_task_url(skylab_task),
                             'skylab.whatever')

  skylab_result = api.skylab.test_api.skylab_result(task=skylab_task)
  api.assertions.assertEqual(
      api.urls.get_skylab_result_link_map(skylab_result),
      {'suite page': 'skylab.whatever'})

  response = ExecuteResponse()
  child_result1 = response.task_results.add()
  child_result1.state.verdict = TaskState.VERDICT_FAILED
  child_result1.name = 'first test'
  child_result1.task_url = 'link.com'
  child_result2 = response.task_results.add()
  child_result2.state.verdict = TaskState.VERDICT_FAILED
  child_result2.name = 'second test'
  child_result2.task_url = 'newlink.com'
  expected_map = {
      'first test': 'link.com',
      'second test': 'newlink.com',
  }
  skylab_result = api.skylab.test_api.skylab_result(
      task=skylab_task, status=common_pb2.FAILURE,
      child_results=response.task_results)
  api.assertions.assertEqual(
      api.urls.get_skylab_result_link_map(skylab_result), expected_map)

  api.assertions.assertEqual(
      api.urls.get_gs_path_url('gs://bucket/a/b/c'),
      'https://storage.cloud.google.com/bucket/a/b/c')
  api.assertions.assertRaises(ValueError, api.urls.get_gs_path_url, 'a/b/c')

  task_state = TaskState(life_cycle=TaskState.LIFE_CYCLE_ABORTED,
                         verdict=TaskState.VERDICT_FAILED)
  api.assertions.assertEqual(
      api.urls.get_state_suffix(task_state), " (Did not run)")


def GenTests(api):
  yield api.test('basic')
