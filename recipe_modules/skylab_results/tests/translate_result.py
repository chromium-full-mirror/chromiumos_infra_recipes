# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.taskstate import TaskState
from PB.test_platform.steps.execution import ExecuteResponse

from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabTask, SkylabResult

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'skylab_results',
]



def RunSteps(api):

  result_json = api.properties.get('result')
  result = json_format.Parse(result_json, ExecuteResponse())
  expected_status = api.properties.get('expected_status')

  task = SkylabTask(id=123, url='', test=None, unit=None)
  skylab_result = api.skylab_results.translate_result(result, task)

  expected_skylab_result = SkylabResult(task=task, status=expected_status,
                                        child_results=result.task_results)
  api.assertions.assertEqual(skylab_result, expected_skylab_result)


def GenTests(api):

  result = ExecuteResponse(state=TaskState(verdict=TaskState.VERDICT_PASSED))
  yield api.test(
      'success',
      api.properties(
          result=json_format.MessageToJson(result),
          expected_status=common_pb2.SUCCESS))

  result = ExecuteResponse(state=TaskState(verdict=TaskState.VERDICT_FAILED))
  yield api.test(
      'failure',
      api.properties(
          result=json_format.MessageToJson(result),
          expected_status=common_pb2.FAILURE))

  result = ExecuteResponse(
      state=TaskState(life_cycle=TaskState.LIFE_CYCLE_ABORTED))
  yield api.test(
      'infra-failure',
      api.properties(
          result=json_format.MessageToJson(result),
          expected_status=common_pb2.INFRA_FAILURE))
