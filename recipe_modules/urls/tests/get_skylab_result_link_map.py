# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for get_skylab_result_link_map."""

from google.protobuf import json_format

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'skylab_results',
    'urls',
]


def RunSteps(api):

  child_results = [
      json_format.Parse(x, ExecuteResponse.TaskResult())
      for x in api.properties.get('child_results', [])
  ]

  skylab_result = api.skylab_results.test_api.skylab_result(
      task=api.skylab_results.test_api.skylab_task(url='skylab.whatever'),
      status=api.properties.get('status', common_pb2.FAILURE),
      child_results=child_results)

  api.assertions.assertDictEqual(
      api.urls.get_skylab_result_link_map(skylab_result),
      dict(api.properties.get('expected_link_map', {})))


def GenTests(api):

  def _task_result(task_result_name='task-1', verdict=TaskState.VERDICT_FAILED,
                   failed_test_names=None, passed_test_names=None,
                   life_cycle=TaskState.LIFE_CYCLE_COMPLETED,
                   provision_verdict=TaskState.VERDICT_PASSED,
                   provision_failure_reason='', attempt=0):

    prejob_steps = [
        ExecuteResponse.TaskResult.TestCaseResult(
            name='provision', human_readable_summary=provision_failure_reason,
            verdict=provision_verdict)
    ] if provision_verdict else []

    test_cases = []
    for test_name in passed_test_names or []:
      test_cases.append(
          ExecuteResponse.TaskResult.TestCaseResult(
              name=test_name, verdict=TaskState.VERDICT_PASSED))
    for test_name in failed_test_names or []:
      test_cases.append(
          ExecuteResponse.TaskResult.TestCaseResult(
              name=test_name, verdict=TaskState.VERDICT_FAILED))

    return json_format.MessageToJson(
        ExecuteResponse.TaskResult(
            name=task_result_name, state=TaskState(life_cycle=life_cycle,
                                                   verdict=verdict),
            attempt=attempt,
            task_url=f'{task_result_name}-attempt-{attempt}-url',
            prejob_steps=prejob_steps, test_cases=test_cases))

  yield api.test(
      'no-child-results-return-suite-page',
      api.properties(expected_link_map={'suite page': 'skylab.whatever'}),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'canceled-while-running',
      api.properties(
          child_results=[_task_result(life_cycle=TaskState.LIFE_CYCLE_ABORTED)],
          expected_link_map={
              'task-1 (canceled while running)': 'task-1-attempt-0-url'
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'test-runner-does-not-get-scheduled',
      api.properties(
          child_results=[
              json_format.MessageToJson(
                  ExecuteResponse.TaskResult(name='task-1-shard-0'))
          ], expected_link_map={'task-1-shard-0': 'skylab.whatever'}),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'success-return-suite-page',
      api.properties(
          status=common_pb2.SUCCESS,
          child_results=[_task_result(verdict=TaskState.VERDICT_PASSED)],
          expected_link_map={'suite page': 'skylab.whatever'}),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'flake-failed-first-passed-latest',
      api.properties(
          child_results=[
              _task_result(
                  failed_test_names=[
                      'some-failed-test', 'some-other-failed-test'
                  ],
              ),
              _task_result(
                  verdict=TaskState.VERDICT_PASSED,
                  passed_test_names=[
                      'some-failed-test', 'some-other-failed-test'
                  ],
                  attempt=1,
              )
          ], expected_link_map={}),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'tauto-tast-wrapper-fails',
      api.properties(
          child_results=[
              json_format.MessageToJson(
                  ExecuteResponse.TaskResult(
                      name='task-1-shard-0', state=TaskState(
                          verdict=TaskState.VERDICT_FAILED,
                          life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
                      test_cases=[
                          ExecuteResponse.TaskResult.TestCaseResult(
                              name='tast',
                              human_readable_summary='failed for a reason',
                              verdict=TaskState.VERDICT_FAILED)
                      ], task_url='some-task.com'))
          ], expected_link_map={'tast: failed for a reason': 'some-task.com'}),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'provision-failure',
      api.properties(
          child_results=[
              _task_result(provision_verdict=TaskState.VERDICT_FAILED)
          ], expected_link_map={
              'task-1 - provision failed': 'task-1-attempt-0-url'
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'provision-failure-with-reason',
      api.properties(
          child_results=[
              _task_result(
                  provision_verdict=TaskState.VERDICT_FAILED,
                  provision_failure_reason='REASON_DUT_UNREACHABLE_POST_PROVISION'
              )
          ], expected_link_map={
              'task-1 - dut_unreachable_post_provision': 'task-1-attempt-0-url'
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'multipe-provision-failures-takes-latest',
      api.properties(
          child_results=[
              _task_result(
                  provision_verdict=TaskState.VERDICT_FAILED,
                  provision_failure_reason='REASON_DUT_UNREACHABLE_POST_PROVISION'
              ),
              _task_result(
                  provision_verdict=TaskState.VERDICT_FAILED,
                  provision_failure_reason='REASON_DUT_UNREACHABLE_POST_PROVISION',
                  attempt=1,
              )
          ], expected_link_map={
              'task-1 - dut_unreachable_post_provision': 'task-1-attempt-1-url'
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'test-case-failure-follow-by-provision-failure-take-first',
      api.properties(
          child_results=[
              _task_result(
                  failed_test_names=[
                      'some-failed-test', 'some-other-failed-test'
                  ],
              ),
              _task_result(
                  provision_verdict=TaskState.VERDICT_FAILED,
                  provision_failure_reason='REASON_DUT_UNREACHABLE_POST_PROVISION',
                  attempt=1,
              )
          ], expected_link_map={
              'some-failed-test': 'task-1-attempt-0-url',
              'some-other-failed-test': 'task-1-attempt-0-url',
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'multiple-test-case-failures-takes-latest',
      api.properties(
          child_results=[
              _task_result(
                  failed_test_names=[
                      'some-failed-test',
                      'some-other-failed-test',
                      'another-failed-test',
                  ],
              ),
              _task_result(
                  failed_test_names=[
                      'some-failed-test',
                      'some-other-failed-test',
                  ],
                  attempt=1,
              ),
              _task_result(
                  failed_test_names=[
                      'some-failed-test',
                  ],
                  attempt=2,
              ),
          ], expected_link_map={
              'some-failed-test': 'task-1-attempt-2-url',
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'multiple-task-result-names',
      api.properties(
          child_results=[
              # Take latest attempt that ran tests.
              _task_result(
                  task_result_name='task-1',
                  failed_test_names=[
                      'some-failed-test',
                      'some-other-failed-test',
                      'another-failed-test',
                  ],
              ),
              _task_result(
                  task_result_name='task-1',
                  failed_test_names=[
                      'some-failed-test',
                      'some-other-failed-test',
                  ],
                  attempt=1,
              ),
              # Take latest attempt that failed provisioning.
              _task_result(
                  task_result_name='task-2',
                  provision_verdict=TaskState.VERDICT_FAILED,
                  provision_failure_reason='REASON_DUT_UNREACHABLE_POST_PROVISION',
              ),
              _task_result(
                  task_result_name='task-2',
                  provision_verdict=TaskState.VERDICT_FAILED,
                  provision_failure_reason='REASON_DUT_UNREACHABLE_POST_PROVISION',
                  attempt=1,
              ),
              # Flaked, does not surface it.
              _task_result(
                  task_result_name='task-3',
                  failed_test_names=[
                      'some-failed-test', 'some-other-failed-test'
                  ],
              ),
              _task_result(
                  task_result_name='task-3',
                  verdict=TaskState.VERDICT_PASSED,
                  passed_test_names=[
                      'some-failed-test', 'some-other-failed-test'
                  ],
                  attempt=1,
              )
          ],
          expected_link_map={
              'some-failed-test': 'task-1-attempt-1-url',
              'some-other-failed-test': 'task-1-attempt-1-url',
              'task-2 - dut_unreachable_post_provision': 'task-2-attempt-1-url',
          }),
      api.post_process(post_process.DropExpectation),
  )
