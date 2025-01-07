# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.steps.execution import ExecuteResponses

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/properties',
    'cros_history',
    'cros_test_proctor',
    'skylab_results',
    'test_util',
]



def RunSteps(api):

  expected_json = api.properties.get('expected_execute_responses')
  expected_tagged_responses = {}
  if expected_json:
    expected_tagged_responses = json_format.Parse(
        expected_json, ExecuteResponses()).tagged_responses

  builds = [
      api.test_util.test_api.test_child_build(build_target_name='target-a',
                                              builder_name='target-a-cq',
                                              revision='aaaaa').message,
      api.test_util.test_api.test_child_build(build_target_name='target-b',
                                              builder_name='target-b-cq',
                                              revision='bbbbb').message,
  ]
  actual_tagged_responses = api.cros_test_proctor._previous_test_results(builds)
  api.assertions.assertCountEqual(actual_tagged_responses,
                                  expected_tagged_responses)


def GenTests(api):
  response_a = ExecuteResponse(task_results=[
      ExecuteResponse.TaskResult(name='tauto.something.something')
  ])
  response_b = ExecuteResponse(
      task_results=[ExecuteResponse.TaskResult(name='tast.something.else')])
  response_c = ExecuteResponse(
      task_results=[ExecuteResponse.TaskResult(name='tast.another.thing')])
  previous_execute_responses = ExecuteResponses(
      tagged_responses={
          'target-a-cq.hw.some_suite': response_a,
          'target-b-cq.some_other_suite': response_b,
          'target-c-cq.some_other_suite': response_c,
      })

  expected_execute_responses = ExecuteResponses(tagged_responses={
      'target-a-cq.hw.some_suite': response_a,
  })

  ctp_build = api.buildbucket.try_build_message(builder='cros_test_platform',
                                                build_id=1)
  ctp_build.output.properties[
      'compressed_responses'] = api.skylab_results.base64_compress_proto(
          previous_execute_responses).decode('utf-8')

  previous_test_summary = [
      {
          'name': 'target-a-cq.hw.some_suite',
          'builder_name': 'target-a-cq',
          'revision': 'aaaaa',
      },
      {
          'name': 'target-b-cq.hw.some_other_suite',
          'builder_name': 'target-b-cq',
          'revision': 'aaaaa',
      },
      {
          'name': 'target-c-cq.hw.some_other_suite',
          'builder_name': 'target-c-cq',
          'revision': 'aaaaa',
      },
  ]

  test_cq_orch = api.cros_history.build_with_test_build_ids_properties([1])
  test_cq_orch.output.properties['test_summary'] = previous_test_summary

  yield api.test(
      'basic',
      api.cv(run_mode=api.cv.FULL_RUN),
      api.buildbucket.simulated_multi_predicates_search_results(
          [test_cq_orch],
          'get previous test results.find matching builds.buildbucket.search'),
      api.buildbucket.simulated_multi_predicates_search_results([
          test_cq_orch
      ], 'get previous test results.find matching builds (2).buildbucket.search'
                                                               ),
      api.buildbucket.simulated_get(
          ctp_build, 'get previous test results.buildbucket.get'),
      api.properties(
          expected_execute_responses=json_format.MessageToJson(
              expected_execute_responses)),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )

  yield api.test(
      'no-previous-test-summary-skip',
      api.cv(run_mode=api.cv.FULL_RUN),
      api.buildbucket.simulated_multi_predicates_search_results(
          [api.cros_history.build_with_test_build_ids_properties([1])],
          'get previous test results.find matching builds.buildbucket.search'),
      api.buildbucket.simulated_multi_predicates_search_results([
          api.cros_history.build_with_test_build_ids_properties([1])
      ], 'get previous test results.find matching builds (2).buildbucket.search'
                                                               ),
      api.buildbucket.simulated_get(
          ctp_build, 'get previous test results.buildbucket.get'),
      api.properties(expected_execute_responses={}),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )
