# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Basic tests for the urls recipe module."""

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as builder_common_pb2
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'urls',
]



def RunSteps(api):
  build = build_pb2.Build(
      id=123,
      builder=builder_common_pb2.BuilderID(builder='something-direct-vm'))

  # Failed test cases is empty.
  build.output.properties.update({'failed_test_cases': []})
  link_map = api.urls.get_vm_test_link_map(build)
  api.assertions.assertEqual(link_map['test page'],
                             'https://cr-buildbucket.appspot.com/build/123')

  # Failed test cases is populated.
  test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name='arc.Boot', verdict=TaskState.VERDICT_FAILED)
  test_case_dict = json_format.MessageToDict(test_case_result)
  build.output.properties.update({'failed_test_cases': [test_case_dict]})
  link_map = api.urls.get_vm_test_link_map(build)
  api.assertions.assertEqual(link_map['arc.Boot'],
                             'https://cr-buildbucket.appspot.com/build/123')


def GenTests(api):
  yield api.test('basic')
