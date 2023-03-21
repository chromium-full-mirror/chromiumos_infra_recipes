# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

from google.protobuf import json_format

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.steps.execution import ExecuteResponses
from PB.test_platform.taskstate import TaskState

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'cros_history',
    'cros_test_proctor',
    'skylab_results',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):

  expected_json = api.properties.get('expected_execute_responses')
  expected_tagged_responses = {}
  if expected_json:
    expected_tagged_responses = json_format.Parse(
        expected_json, ExecuteResponses()).tagged_responses

  actual_tagged_responses = api.cros_test_proctor._previous_test_results()
  api.assertions.assertCountEqual(actual_tagged_responses,
                                  expected_tagged_responses)


def GenTests(api):

  def execute_responses():
    r = ExecuteResponse()
    tr = r.task_results.add()
    tr.name = 'tauto.something.something'
    tr.state.life_cycle = TaskState.LIFE_CYCLE_COMPLETED
    return ExecuteResponses(tagged_responses={'something': r})

  ctp_build = api.buildbucket.try_build_message(builder='cros_test_platform',
                                                build_id=1)
  ctp_build.output.properties[
      'compressed_responses'] = api.skylab_results.base64_compress_proto(
          execute_responses()).decode('utf-8')

  yield api.test(
      'not-elegible',
      api.buildbucket.try_build(builder='cq-orchestrator'),
      api.properties(
          expected_execute_responses=json_format.MessageToJson(
              ExecuteResponses())),
      api.post_check(post_process.DoesNotRun, 'find matching builds'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'elegible',
      api.buildbucket.try_build(
          experiments=['chromeos.skylab.direct_tast_testing']),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_test_build_ids_properties([1], [2, 3])],
          'find matching builds.buildbucket.search'),
      api.buildbucket.simulated_get(ctp_build),
      api.properties(
          expected_execute_responses=json_format.MessageToJson(
              execute_responses())),
      api.post_process(post_process.DropExpectation),
  )
