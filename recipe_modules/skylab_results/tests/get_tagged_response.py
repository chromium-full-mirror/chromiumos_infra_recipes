# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf.json_format import MessageToDict

from PB.test_platform.taskstate import TaskState
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.steps.execution import ExecuteResponses

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'skylab_results',
]



def RunSteps(api):

  # Build without the compressed_response output property returns the default.
  build = api.buildbucket.build
  responses = api.skylab_results.get_tagged_execute_responses_from_build(build)
  api.assertions.assertEqual(responses, ExecuteResponses().tagged_responses)

  # Build with a compressed_response output property returns a tagged response.
  build = api.skylab_results.test_api.test_with_multi_response(
      1234, names=['htarget.hw.bvt-cq'],
      task_state=TaskState(verdict=TaskState.VERDICT_PASSED))
  responses = api.skylab_results.get_tagged_execute_responses_from_build(build)

  execute_response = responses.get('htarget.hw.bvt-cq')
  expected_execute_resonse_subset = ExecuteResponse(
      state=TaskState(verdict=TaskState.VERDICT_PASSED))
  api.assertions.assertDictContainsSubset(
      MessageToDict(expected_execute_resonse_subset),
      MessageToDict(execute_response))


def GenTests(api):

  yield api.test('basic')
