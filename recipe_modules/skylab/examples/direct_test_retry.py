# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import duration_pb2

from PB.chromiumos.test.api.test_suite import TestSuite
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_test_plan',
    'metadata',
    'skylab',
]



def RunSteps(api):
  hw_test_unit = api.cros_test_plan.test_api.hw_test_unit
  hw_test = hw_test_unit.hw_test_cfg.hw_test[0]
  hw_test.run_via_cft = True
  hw_test.tag_criteria.CopyFrom(TestSuite.TestCaseTagCriteria(tags=['hi']))
  hw_test.common.display_name = 'tast-first-class'
  unit_hw_test = UnitHwTest(unit=hw_test_unit, hw_test=hw_test)

  some_other_hw_test_unit = api.cros_test_plan.test_api.some_other_hw_test_unit
  some_other_hw_test = some_other_hw_test_unit.hw_test_cfg.hw_test[0]
  some_other_hw_test.run_via_cft = True
  some_other_hw_test.common.display_name = 'not-tast-first-class'
  some_other_unit_hw_test = UnitHwTest(unit=some_other_hw_test_unit,
                                       hw_test=some_other_hw_test)

  another_hw_test_unit = api.cros_test_plan.test_api.another_hw_test_unit
  another_hw_test = another_hw_test_unit.hw_test_cfg.hw_test[0]
  another_hw_test.common.display_name = 'not-cft'
  another_unit_hw_test = UnitHwTest(unit=another_hw_test_unit,
                                    hw_test=another_hw_test)

  previous_results = {
      'tast-first-class':
          ExecuteResponse(task_results=[
              ExecuteResponse.TaskResult(
                  name='tast.shard-0', state=TaskState(
                      life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
                  prejob_steps=[
                      ExecuteResponse.TaskResult.TestCaseResult(
                          name='provision', verdict=TaskState.VERDICT_PASSED)
                  ], test_cases=[
                      ExecuteResponse.TaskResult.TestCaseResult(
                          name='tast.test1', verdict=TaskState.VERDICT_FAILED)
                  ])
          ]),
      'not-tast-first-class':
          ExecuteResponse(task_results=[
              ExecuteResponse.TaskResult(
                  name='tast.shard-0', state=TaskState(
                      life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
                  prejob_steps=[
                      ExecuteResponse.TaskResult.TestCaseResult(
                          name='provision', verdict=TaskState.VERDICT_PASSED)
                  ], test_cases=[
                      ExecuteResponse.TaskResult.TestCaseResult(
                          name='tast.test1', verdict=TaskState.VERDICT_FAILED)
                  ])
          ]),
      'not-cft':
          ExecuteResponse(task_results=[
              ExecuteResponse.TaskResult(
                  name='tast.shard-0', state=TaskState(
                      life_cycle=TaskState.LIFE_CYCLE_COMPLETED),
                  prejob_steps=[
                      ExecuteResponse.TaskResult.TestCaseResult(
                          name='provision', verdict=TaskState.VERDICT_PASSED)
                  ], test_cases=[
                      ExecuteResponse.TaskResult.TestCaseResult(
                          name='tast.test1', verdict=TaskState.VERDICT_FAILED)
                  ])
          ])
  }
  api.skylab.schedule_suites(
      [unit_hw_test, some_other_unit_hw_test, another_unit_hw_test],
      timeout=duration_pb2.Duration(seconds=3600),
      container_metadata=api.metadata.test_api.mock_metadata(target='target'),
      previous_results=previous_results)


def GenTests(api):

  build = api.buildbucket.try_build_message(status='FAILURE')
  build.output.properties['tast_first_class_tests'] = ['tast-first-class']

  yield api.test(
      'basic',
      api.buildbucket.try_build(
          experiments=['chromeos.skylab.direct_tast_testing']),
      api.buildbucket.simulated_search_results(
          [build], 'schedule skylab tests v2.'
          'create test requests.configure test-builder.'
          'find matching builds.buildbucket.search'),
      api.post_check(lambda check, steps: check('tast.test1' in steps[
          'schedule skylab tests v2.create test requests.configure test-builder'
      ].logs['request'])),
      api.post_check(lambda check, steps: check('tast.shard-0' in steps[
          'schedule skylab tests v2.create test requests.configure test-builder (2)'
      ].logs['request'])),
      # Non-CFT test suites are not elegible for direct test retries during the
      # initial rollout.
      api.post_check(lambda check, steps: check('tast.shard-0' not in steps[
          'schedule skylab tests v2.create test requests.configure test-builder (3)'
      ].logs['request'])),
      api.post_check(lambda check, steps: check('tast.test1' not in steps[
          'schedule skylab tests v2.create test requests.configure test-builder (3)'
      ].logs['request'])),
  )
