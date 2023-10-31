# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from google.protobuf import json_format

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.recipe_modules.chromeos.exonerate.exonerate import FailedTestStats
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.steps.execution import ExecuteResponses
from PB.test_platform.taskstate import TaskState
from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_RETRY_PREJOB_FAILURES

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'auto_retry_util',
    'cros_history',
    'skylab_results',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  updated_failed_test_stats = [
      FailedTestStats(test_id='fake.test', build_target='d',
                      automatically_exonerated=True),
      FailedTestStats(test_id='fake.test', build_target='b',
                      automatically_exonerated=True),
  ]
  exonerated_suites = api.auto_retry_util.get_exonerated_suites(
      api.buildbucket.build, updated_failed_test_stats)
  expected_exonerated_suites = api.properties.get('expected_exonerated_suites')
  api.assertions.assertCountEqual(exonerated_suites, expected_exonerated_suites)


def GenTests(api):

  # HW test results mock data.
  execute_responses = ExecuteResponses(
      tagged_responses={
          'a-cq.hw.suite':
              ExecuteResponse(
                  state=TaskState(verdict=TaskState.VERDICT_FAILED,
                                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
                  task_results=[
                      ExecuteResponse.TaskResult(
                          name='suite', state=TaskState(
                              verdict=TaskState.VERDICT_FAILED), test_cases=[
                                  ExecuteResponse.TaskResult.TestCaseResult(
                                      name='anotherFake.test',
                                      verdict=TaskState.VERDICT_FAILED)
                              ]),
                  ]),
          'b-cq.hw.suite':
              ExecuteResponse(
                  state=TaskState(verdict=TaskState.VERDICT_FAILED,
                                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
                  task_results=[
                      ExecuteResponse.TaskResult(
                          name='suite', state=TaskState(
                              verdict=TaskState.VERDICT_FAILED), test_cases=[
                                  ExecuteResponse.TaskResult.TestCaseResult(
                                      name='fake.test',
                                      verdict=TaskState.VERDICT_FAILED)
                              ]),
                  ]),
          'e-cq.hw.suite':
              ExecuteResponse(
                  state=TaskState(verdict=TaskState.VERDICT_FAILED,
                                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
                  task_results=[
                      ExecuteResponse.TaskResult(
                          name='suite-shard-0', state=TaskState(
                              verdict=TaskState.VERDICT_FAILED), prejob_steps=[
                                  ExecuteResponse.TaskResult.TestCaseResult(
                                      name='prejob-step',
                                      verdict=TaskState.VERDICT_FAILED)
                              ]),
                      ExecuteResponse.TaskResult(
                          name='suite-shard-1', state=TaskState(
                              verdict=TaskState.VERDICT_PASSED), prejob_steps=[
                                  ExecuteResponse.TaskResult.TestCaseResult(
                                      name='prejob-step',
                                      verdict=TaskState.VERDICT_PASSED)
                              ]),
                  ]),
          'h-cq.hw.cq-minimal':
              ExecuteResponse(
                  state=TaskState(verdict=TaskState.VERDICT_FAILED,
                                  life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
                  task_results=[
                      ExecuteResponse.TaskResult(
                          name='suite-shard-0', state=TaskState(
                              verdict=TaskState.VERDICT_FAILED), prejob_steps=[
                                  ExecuteResponse.TaskResult.TestCaseResult(
                                      name='prejob-step',
                                      verdict=TaskState.VERDICT_FAILED)
                              ]),
                  ]),
      })
  ctp_build = build_pb2.Build(id=111, status='FAILURE')
  ctp_build.output.properties.update({
      'compressed_responses':
          api.skylab_results.base64_compress_proto(execute_responses).decode()
  })

  # VM test results mock data.
  vm_build_1 = build_pb2.Build(
      id=222, builder=builder_common_pb2.BuilderID(builder='c-cq'),
      status='FAILURE')
  vm_build_1.input.properties.update({
      'name': 'c-cq.tast_vm.suite',
      'buildTarget': json_format.MessageToDict(BuildTarget(name='c'))
  })
  test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name='fake.anotherTest', verdict=TaskState.VERDICT_FAILED)
  vm_build_1.output.properties.update(
      {'failed_test_cases': [json_format.MessageToDict(test_case_result)]})

  vm_build_2 = build_pb2.Build(
      id=222, builder=builder_common_pb2.BuilderID(builder='d-cq'),
      status='FAILURE')
  vm_build_2.input.properties.update({
      'name': 'd-cq.tast_gce.suite',
      'buildTarget': json_format.MessageToDict(BuildTarget(name='d'))
  })
  test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name='fake.test', verdict=TaskState.VERDICT_FAILED)
  vm_build_2.output.properties.update(
      {'failed_test_cases': [json_format.MessageToDict(test_case_result)]})

  test_summary = [
      # HW test results.
      {
          'builder_name': 'a-cq',
          'build_target': 'a',
          'board': 'a',
          'status': 'FAILURE',
          'critical': True,
          'name': 'a-cq.hw.suite'
      },
      {
          'builder_name': 'b-cq',
          'build_target': 'b',
          'board': 'b',
          'status': 'FAILURE',
          'critical': True,
          'name': 'b-cq.hw.suite'
      },
      {
          'builder_name': 'e-cq',
          'build_target': 'e',
          'board': 'e',
          'status': 'FAILURE',
          'critical': True,
          'name': 'e-cq.hw.suite'
      },
      {
          'builder_name': 'h-cq',
          'build_target': 'h',
          'board': 'h',
          'status': 'FAILURE',
          'critical': True,
          'name': 'h-cq.hw.cq-minimal'
      },
      # VM test results.
      {
          'builder_name': 'c-cq',
          'build_target': 'c',
          'status': 'FAILURE',
          'critical': True,
          'name': 'c-cq.tast_vm.suite'
      },
      {
          'builder_name': 'd-cq',
          'build_target': 'd',
          'board': 'd',
          'status': 'FAILURE',
          'critical': True,
          'name': 'd-cq.tast_gce.suite'
      },
  ]

  yield api.test(
      'basic',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111],
                  'tast_vm_tests_builder_ids': [222, 333]
              }
          }).build,
      api.buildbucket.simulated_get_multi(
          [ctp_build], 'get previous skylab tasks v2.buildbucket.get_multi'),
      api.buildbucket.simulated_get_multi([vm_build_1, vm_build_2]),
      api.properties(
          expected_exonerated_suites=['b-cq.hw.suite', 'd-cq.tast_gce.suite']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'some-previously-exonerated',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111],
                  'tast_vm_tests_builder_ids': [222, 333]
              },
              'passed_tests': ['b-cq.hw.suite'],
          }).build,
      api.buildbucket.simulated_get_multi(
          [ctp_build], 'get previous skylab tasks v2.buildbucket.get_multi'),
      api.buildbucket.simulated_get_multi([vm_build_1, vm_build_2]),
      api.properties(expected_exonerated_suites=['d-cq.tast_gce.suite']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'exoneration-overridden',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111],
                  'tast_vm_tests_builder_ids': [222, 333]
              }
          }).build,
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(overall_autoex_limit=1)}),
      api.properties(expected_exonerated_suites=[]),
      api.post_check(post_process.DoesNotRun, 'get previous skylab tasks v2'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'prejob-exoneration-experimental-feature',
      api.test_util.test_orchestrator(
          cq=True, output_properties={
              'test_summary': test_summary,
              'test_tasks': {
                  'skylab_builder_ids': [111],
                  'tast_vm_tests_builder_ids': [222, 333]
              }
          }).build,
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_RETRY_PREJOB_FAILURES)
                  ])
          }),
      api.buildbucket.simulated_get_multi(
          [ctp_build], 'get previous skylab tasks v2.buildbucket.get_multi'),
      api.buildbucket.simulated_get_multi([vm_build_1, vm_build_2]),
      api.properties(expected_exonerated_suites=[
          'b-cq.hw.suite',
          'd-cq.tast_gce.suite',
          'e-cq.hw.suite',
          'h-cq.hw.cq-minimal',
      ]),
      api.post_process(post_process.DropExpectation),
  )
