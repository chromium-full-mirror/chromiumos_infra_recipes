# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the had_no_unexpected_skips function."""

from google.protobuf import json_format

from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState
from RECIPE_MODULES.chromeos.tast_results.api import MISSING_TEST_FAILURE_SUMMARY

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'tast_results',
]



def RunSteps(api):
  expected_response = api.properties['expected_response']
  vm_test_build = api.buildbucket.build
  api.assertions.assertEqual(
      expected_response,
      api.tast_results.had_no_unexpected_skips(vm_test_build))


def GenTests(api):

  yield api.test(
      'successful-build',
      api.buildbucket.ci_build(status='SUCCESS'),
      api.properties(expected_response=True),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-test-cases',
      api.buildbucket.ci_build(status='FAILURE'),
      api.properties(expected_response=False),
      api.post_process(post_process.DropExpectation),
  )

  vm_build = api.buildbucket.ci_build_message(status='FAILURE')
  test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name='fake.test', verdict=TaskState.VERDICT_FAILED)
  vm_build.output.properties.update(
      {'failed_test_cases': [json_format.MessageToDict(test_case_result)]})

  yield api.test(
      'no-unexpected-skipped-test-cases',
      api.buildbucket.build(vm_build),
      api.properties(expected_response=True),
      api.post_process(post_process.DropExpectation),
  )

  vm_build = api.buildbucket.ci_build_message(status='FAILURE')
  test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name='fake.test', verdict=TaskState.VERDICT_FAILED,
      human_readable_summary=MISSING_TEST_FAILURE_SUMMARY)
  vm_build.output.properties.update(
      {'failed_test_cases': [json_format.MessageToDict(test_case_result)]})

  yield api.test(
      'unexpected-skipped-test-cases',
      api.buildbucket.build(vm_build),
      api.properties(expected_response=False),
      api.post_process(post_process.DropExpectation),
  )
