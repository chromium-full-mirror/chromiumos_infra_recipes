# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Basic tests for the urls recipe module."""

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'tast_results',
    'urls',
]


def RunSteps(api):
  build = build_pb2.Build(
      id=123, builder=build_pb2.BuilderID(builder='something-direct-vm'))
  test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name='arc.Boot', verdict=TaskState.VERDICT_FAILED)
  task_result = ExecuteResponse.TaskResult(test_cases=[test_case_result])
  task_result_dict = json_format.MessageToDict(task_result)
  build.output.properties.update({'task_result': task_result_dict})
  api.urls.get_vm_test_link_map(build)


def GenTests(api):
  yield api.test('basic')
