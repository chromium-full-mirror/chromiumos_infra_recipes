# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the get_per_board_prejob_stats function."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

from recipe_engine import post_process
from RECIPE_MODULES.chromeos.skylab_results.api import PrejobStats
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult, SkylabTask

DEPS = [
    'recipe_engine/assertions',
    'skylab_results',
]



def RunSteps(api):

  # Set up test data.
  skylab_results = []

  # board-a is used by two suites.
  board_a_hw_test = HwTestCfg.HwTest(skylab_board='board-a')
  task = SkylabTask(id='', url='', test=board_a_hw_test, unit='')

  # board-a suite 1 results.
  child_results = [
      # Passed prejob steps.
      ExecuteResponse.TaskResult(
          name='board-a-suite-1-shard-0', prejob_steps=[
              ExecuteResponse.TaskResult.TestCaseResult(
                  name='provision', verdict=TaskState.VERDICT_PASSED)
          ]),
      # Failed one prejob step.
      ExecuteResponse.TaskResult(
          name='board-a-suite-1-shard-1', prejob_steps=[
              ExecuteResponse.TaskResult.TestCaseResult(
                  name='provision', verdict=TaskState.VERDICT_PASSED),
              ExecuteResponse.TaskResult.TestCaseResult(
                  name='another-prejob-step', verdict=TaskState.VERDICT_FAILED),
          ]),
  ]
  skylab_results.append(
      SkylabResult(task=task, status=common_pb2.FAILURE,
                   child_results=child_results))

  # board-a suite 2 results.
  child_results = [
      # Passed all prejob steps.
      ExecuteResponse.TaskResult(
          name='board-a-suite-2-shard-0', prejob_steps=[
              ExecuteResponse.TaskResult.TestCaseResult(
                  name='provision', verdict=TaskState.VERDICT_PASSED)
          ]),
  ]
  skylab_results.append(
      SkylabResult(task=task, status=common_pb2.SUCCESS,
                   child_results=child_results))

  # board-b did not run prejob steps.
  board_b_hw_test = HwTestCfg.HwTest(skylab_board='board-b')
  task = SkylabTask(id='', url='', test=board_b_hw_test, unit='')
  child_results = [
      # Passed all prejob steps.
      ExecuteResponse.TaskResult(name='board-a-suite-2-shard-0',
                                 prejob_steps=[]),
  ]
  skylab_results.append(
      SkylabResult(task=task, status=common_pb2.FAILURE,
                   child_results=child_results))

  # Test get_per_board_prejob_stats.
  prejob_stats_map = api.skylab_results.get_per_board_prejob_stats(
      skylab_results)
  expected_prejob_stats_map = {
      'board-a': PrejobStats(failed=1, succeeded=2),
      'board-b': PrejobStats(),
  }
  api.assertions.assertDictEqual(expected_prejob_stats_map, prejob_stats_map)


def GenTests(api):

  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )
