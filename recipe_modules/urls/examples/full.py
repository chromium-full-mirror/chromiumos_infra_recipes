# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Basic tests for the urls recipe module."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'skylab_results',
    'urls',
]



def RunSteps(api):
  build = build_pb2.Build(id=123)
  api.assertions.assertEqual(
      api.urls.get_build_link_map(build),
      {'build page': api.buildbucket.build_url(build_id=123)})

  build = build_pb2.Build(id=123)
  api.assertions.assertEqual(
      api.urls.get_vm_test_link_map(build),
      {'test page': api.buildbucket.build_url(build_id=123)})

  skylab_task = api.skylab_results.test_api.skylab_task(url='skylab.whatever')
  api.assertions.assertEqual(
      api.urls.get_skylab_task_url(skylab_task), 'skylab.whatever')

  skylab_result = api.skylab_results.test_api.skylab_result(task=skylab_task)
  api.assertions.assertEqual(
      api.urls.get_skylab_result_link_map(skylab_result),
      {'suite page': 'skylab.whatever'})

  # Case when the task is never scheduled so the result does not have a url.
  response = ExecuteResponse()
  child_result1 = response.task_results.add()
  child_result1.state.verdict = TaskState.VERDICT_FAILED
  child_result1.state.life_cycle = TaskState.LIFE_CYCLE_REJECTED
  child_result1.name = 'first test'
  skylab_result = api.skylab_results.test_api.skylab_result(
      task=skylab_task, child_results=response.task_results,
      status=common_pb2.FAILURE)
  api.assertions.assertEqual(
      api.urls.get_skylab_result_link_map(skylab_result),
      {'first test (never ran, due to no DUT capacity)': 'skylab.whatever'})

  response = ExecuteResponse()
  child_result1 = response.task_results.add()
  child_result1.state.verdict = TaskState.VERDICT_FAILED
  child_result1.state.life_cycle = TaskState.LIFE_CYCLE_COMPLETED
  child_result1.name = 'first test'
  child_result1.task_url = 'link.com'
  prejob_step1 = child_result1.prejob_steps.add()
  prejob_step1.verdict = TaskState.VERDICT_FAILED
  prejob_step1.name = 'provision'
  test_case0 = child_result1.test_cases.add()
  test_case0.name = 'test0'
  test_case0.verdict = TaskState.VERDICT_UNSPECIFIED
  test_case1 = child_result1.test_cases.add()
  test_case1.name = 'test1'
  test_case1.verdict = TaskState.VERDICT_NO_VERDICT

  expected_map = {
      'first test - provision failed': 'link.com',
  }
  skylab_result = api.skylab_results.test_api.skylab_result(
      task=skylab_task, status=common_pb2.FAILURE,
      child_results=response.task_results)
  api.assertions.assertEqual(
      api.urls.get_skylab_result_link_map(skylab_result), expected_map)

  prejob_step1.human_readable_summary = 'REASON_DUT_UNREACHABLE_POST_PROVISION'
  expected_map = {
      'first test - dut_unreachable_post_provision': 'link.com',
  }
  skylab_result = api.skylab_results.test_api.skylab_result(
      task=skylab_task, status=common_pb2.FAILURE,
      child_results=response.task_results)
  api.assertions.assertEqual(
      api.urls.get_skylab_result_link_map(skylab_result), expected_map)

  response = ExecuteResponse()
  child_result1 = response.task_results.add()
  child_result1.state.verdict = TaskState.VERDICT_FAILED
  child_result1.name = 'first test'
  child_result1.task_url = 'link.com'
  child_result2 = response.task_results.add()
  child_result2.state.verdict = TaskState.VERDICT_FAILED
  child_result2.state.life_cycle = TaskState.LIFE_CYCLE_COMPLETED
  child_result2.name = 'second test'
  child_result2.task_url = 'newlink.com'
  test_case0 = child_result2.test_cases.add()
  test_case0.name = 'tast'
  test_case0.verdict = TaskState.VERDICT_FAILED
  test_case0.human_readable_summary = 'failed because reasons'
  test_case1 = child_result2.test_cases.add()
  test_case1.name = 'tast.speaker.IsReallyLoud'
  test_case1.verdict = TaskState.VERDICT_FAILED
  test_case2 = child_result2.test_cases.add()
  test_case2.name = 'tast.cpu.IsVeryFast'
  test_case2.verdict = TaskState.VERDICT_FAILED
  test_case2.human_readable_summary = 'failed because it was just too fast'
  # Flaked child result should not be surfaced on UI.
  child_result3 = response.task_results.add()
  child_result3.name = 'third test'
  child_result3.state.verdict = TaskState.VERDICT_FAILED
  child_result4 = response.task_results.add()
  child_result4.name = 'third test'
  child_result4.state.verdict = TaskState.VERDICT_PASSED

  expected_map = {
      'tast: failed because reasons': 'newlink.com',
      'first test': 'link.com',
      'tast.speaker.IsReallyLoud': 'newlink.com',
      'tast.cpu.IsVeryFast': 'newlink.com',
  }
  skylab_result = api.skylab_results.test_api.skylab_result(
      task=skylab_task, status=common_pb2.FAILURE,
      child_results=response.task_results)
  api.assertions.assertEqual(
      api.urls.get_skylab_result_link_map(skylab_result), expected_map)

  api.assertions.assertEqual(
      api.urls.get_gs_path_url('gs://bucket/a/b/c'),
      'https://storage.cloud.google.com/bucket/a/b/c')
  # Test a path where the bucket starts with 'gs', to make sure it doesn't
  # get stripped as well.
  api.assertions.assertEqual(
      api.urls.get_gs_path_url('gs://gs-test/a/b'),
      'https://storage.cloud.google.com/gs-test/a/b')
  api.assertions.assertRaises(ValueError, api.urls.get_gs_path_url, 'a/b/c')

  api.assertions.assertEqual(
      api.urls.get_gs_bucket_url('bucket-name', 'path/to/file'),
      'https://console.cloud.google.com/storage/browser/_details/' +
      'bucket-name/path/to/file')

  task_state = TaskState(life_cycle=TaskState.LIFE_CYCLE_ABORTED,
                         verdict=TaskState.VERDICT_FAILED)
  api.assertions.assertEqual(
      api.urls.get_state_suffix(task_state), ' (canceled while running)')
  for life_cycle in [
      TaskState.LIFE_CYCLE_CANCELLED, TaskState.LIFE_CYCLE_RUNNING,
      TaskState.LIFE_CYCLE_ABORTED, TaskState.LIFE_CYCLE_REJECTED,
      TaskState.LIFE_CYCLE_PENDING
  ]:
    api.urls.get_state_suffix(
        TaskState(life_cycle=life_cycle, verdict=TaskState.VERDICT_FAILED))

  with api.step.nest('outer step') as pres:
    step_result = api.step('run cmd on a/b', ['ls'])
    pres.logs['customlog'] = 'new info'
    api.assertions.assertEqual(
        api.urls.get_logdog_url(step_result, 'customlog',
                                use_top_level_step=True),
        'https://logs.chromium.org/logs/chromeos/logdog/prefix/+/u/outer_step/customlog',
    )
    api.assertions.assertEqual(
        api.urls.get_logdog_url(step_result, 'customlog',
                                use_top_level_step=False),
        'https://logs.chromium.org/logs/chromeos/logdog/prefix/+/u/outer_step/run_cmd_on_a_b/customlog',
    )


def GenTests(api):
  # Populate logdog fields on the build message so link components are filled
  # out.
  build_message = api.buildbucket.ci_build_message(build_id=123)
  build_message.infra.logdog.hostname = 'logs.chromium.org'
  build_message.infra.logdog.project = 'chromeos'
  build_message.infra.logdog.prefix = 'logdog/prefix'

  yield api.test(
      'basic',
      api.buildbucket.build(build_message),
  )
