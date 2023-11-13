# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the get_failure_attributed_hw_suites method."""

from typing import List, Optional

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.steps.execution import ExecuteResponses
from PB.test_platform.taskstate import TaskState

from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'auto_retry_util',
    'cros_infra_config',
    'skylab_results',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  failure_attributed_suites = api.auto_retry_util.get_failure_attributed_hw_suites(
      api.buildbucket.build,
      already_retryable_suites=api.properties.get('already_retryable_suites'))
  expected_failure_attributed_suites = api.properties.get(
      'expected_failure_attributed_suites')
  api.assertions.assertCountEqual(failure_attributed_suites,
                                  expected_failure_attributed_suites)


def GenTests(api):

  def get_ctp_build(
      verdicts: Optional[List[Optional[TaskState.Verdict]]] = None
  ) -> build_pb2.Build:
    if not verdicts:
      verdicts = [
          TaskState.Verdict.VERDICT_FAILED, TaskState.Verdict.VERDICT_FAILED
      ]

    task_verdict = TaskState.Verdict.VERDICT_PASSED if all(
        v == TaskState.Verdict.VERDICT_PASSED
        for v in verdicts) else TaskState.Verdict.VERDICT_FAILED

    execute_responses = ExecuteResponses(
        tagged_responses={
            'a-cq.hw.suite':
                ExecuteResponse(
                    state=TaskState(verdict=task_verdict,
                                    life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
                    task_results=[
                        ExecuteResponse.TaskResult(
                            name='suite',
                            state=TaskState(verdict=TaskState.VERDICT_FAILED),
                            test_cases=[
                                ExecuteResponse.TaskResult.TestCaseResult(
                                    name=f'fake.test{i+1}', verdict=verdict)
                                for i, verdict in enumerate(verdicts)
                            ],
                        ),
                    ]),
        })

    ctp_build = build_pb2.Build(id=111, status=common_pb2.FAILURE)
    ctp_build.output.properties.update({
        'compressed_responses':
            api.skylab_results.base64_compress_proto(execute_responses
                                                    ).decode()
    })

    return ctp_build

  test_summary = [
      {
          'builder_name': 'a-cq',
          'build_target': 'a',
          'board': 'a',
          'status': 'FAILURE',
          'critical': True,
          'name': 'a-cq.hw.suite'
      },
  ]

  yield api.test(
      'matching-failure-is-attributed',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111]
              },
              'cq_fault_attributions': {
                  'test_failure_attributions': [{
                      'build_target':
                          'a',
                      'fault_attributes': [
                          {
                              'test_name':
                                  'fake.test1',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          },
                          {
                              'test_name':
                                  'fake.test2',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          },
                      ]
                  },]
              }
          }).build,
      api.buildbucket.simulated_get_multi([
          get_ctp_build()
      ], 'get attributed hw suites.get previous skylab tasks v2.buildbucket.get_multi'
                                         ),
      api.properties(
          expected_failure_attributed_suites=['a-cq.hw.suite'],
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES)
                  ])
          },
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'already-retryable-is-not-attributed',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111]
              },
              'cq_fault_attributions': {
                  'test_failure_attributions': [{
                      'build_target':
                          'a',
                      'fault_attributes': [
                          {
                              'test_name':
                                  'fake.test1',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          },
                          {
                              'test_name':
                                  'fake.test2',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          },
                      ]
                  },]
              }
          }).build,
      api.buildbucket.simulated_get_multi([
          get_ctp_build()
      ], 'get attributed hw suites.get previous skylab tasks v2.buildbucket.get_multi'
                                         ),
      api.properties(
          already_retryable_suites=['a-cq.hw.suite'],
          expected_failure_attributed_suites=[],
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES)
                  ])
          },
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'different-failure-is-not-attributed',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111]
              },
              'cq_fault_attributions': {
                  'test_failure_attributions': [{
                      'build_target':
                          'a',
                      'fault_attributes': [{
                          'test_name':
                              'fake.test1',
                          'snapshot_comparison_fault_attribution':
                              'DIFFERING_FAILURE_FOUND',
                      }, {
                          'test_name':
                              'fake.test2',
                          'snapshot_comparison_fault_attribution':
                              'MATCHING_FAILURE_FOUND',
                      }]
                  },]
              }
          }).build,
      api.buildbucket.simulated_get_multi([
          get_ctp_build()
      ], 'get attributed hw suites.get previous skylab tasks v2.buildbucket.get_multi'
                                         ),
      api.properties(
          expected_failure_attributed_suites=[],
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES)
                  ])
          },
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'matching-failure-on-different-build-target-is-attributed',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111]
              },
              'cq_fault_attributions': {
                  'test_failure_attributions': [
                      {
                          'build_target':
                              'b',
                          'fault_attributes': [{
                              'test_name':
                                  'fake.test1',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          }]
                      },
                      {
                          'build_target':
                              'a',
                          'fault_attributes': [{
                              'test_name':
                                  'fake.test2',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          }]
                      },
                  ]
              }
          }).build,
      api.buildbucket.simulated_get_multi([
          get_ctp_build()
      ], 'get attributed hw suites.get previous skylab tasks v2.buildbucket.get_multi'
                                         ),
      api.properties(
          expected_failure_attributed_suites=['a-cq.hw.suite'],
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES)
                  ])
          },
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'experiment-not-enabled',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111]
              },
              'cq_fault_attributions': {
                  'test_failure_attributions': [{
                      'build_target':
                          'a',
                      'fault_attributes': [{
                          'test_name':
                              'fake.test',
                          'snapshot_comparison_fault_attribution':
                              'MATCHING_FAILURE_FOUND',
                      }]
                  },]
              }
          }).build,
      api.properties(
          expected_failure_attributed_suites=[],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-verdict-is-not-attributed',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111]
              },
              'cq_fault_attributions': {
                  'test_failure_attributions': [{
                      'build_target':
                          'a',
                      'fault_attributes': [
                          {
                              'test_name':
                                  'fake.test1',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          },
                          {
                              'test_name':
                                  'fake.test2',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          },
                      ]
                  },]
              }
          }).build,
      api.buildbucket.simulated_get_multi([
          get_ctp_build(
              [TaskState.VERDICT_PASSED, TaskState.VERDICT_NO_VERDICT])
      ], 'get attributed hw suites.get previous skylab tasks v2.buildbucket.get_multi'
                                         ),
      api.properties(
          expected_failure_attributed_suites=[],
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES)
                  ])
          },
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'successful-ctp-build-is-not-attributed',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111]
              },
              'cq_fault_attributions': {
                  'test_failure_attributions': [{
                      'build_target':
                          'a',
                      'fault_attributes': [
                          {
                              'test_name':
                                  'fake.test1',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          },
                          {
                              'test_name':
                                  'fake.test2',
                              'snapshot_comparison_fault_attribution':
                                  'MATCHING_FAILURE_FOUND',
                          },
                      ]
                  },]
              }
          }).build,
      api.buildbucket.simulated_get_multi([
          get_ctp_build([TaskState.VERDICT_PASSED, TaskState.VERDICT_PASSED])
      ], 'get attributed hw suites.get previous skylab tasks v2.buildbucket.get_multi'
                                         ),
      api.properties(
          expected_failure_attributed_suites=[],
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES)
                  ])
          },
      ),
      api.post_process(post_process.DropExpectation),
  )
