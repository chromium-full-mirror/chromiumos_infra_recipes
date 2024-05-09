# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/properties',
    'exonerate',
    'skylab_results',
]


def RunSteps(api):
  fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
  failing_exonerable_test_cases = [
      ExecuteResponse.TaskResult.TestCaseResult(
          name='test2', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='line 22: error'),
  ]
  child_results = [
      ExecuteResponse.TaskResult(name='suite2', state=fail_state,
                                 test_cases=failing_exonerable_test_cases),
  ]
  hw_test_failures = [
      api.skylab_results.test_api.skylab_result(
          task=api.skylab_results.test_api.skylab_task(),
          status=common_pb2.FAILURE, child_results=child_results),
  ]

  _, _ = api.exonerate.exonerate_hwtests(hw_test_failures)
  api.exonerate.auto_exoneration_analysis()
  api.exonerate.auto_exoneration_analysis(fake_data=True)


def GenTests(api):
  yield api.test(
      'dont-fail-on-auto-exoneration',
      api.properties(
          **{
              '$chromeos/exonerate':
                  ExonerateProperties(enable_exoneration=True, dry_run=True)
          }),
      api.step_data(
          'Automated Exoneration Analysis.query LUCI Analysis for failure rates.rpc call',
          retcode=1),
      api.post_process(post_process.StepSuccess,
                       'Automated Exoneration Analysis'),
      api.post_process(post_process.DropExpectation))
