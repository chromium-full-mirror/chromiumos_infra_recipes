# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'tast_results',
    'cros_tags',
]



def RunSteps(api):
  temp_dir = api.path.mkdtemp(prefix='test-results')

  # Test not having any tests to run (like in an empty shard).
  task_result = api.tast_results.get_results(
      temp_dir, 'reven-vmtest-cq.tast_vm.tast_vm_default', '1', [], 'gs://url')
  api.assertions.assertEqual(task_result.state.verdict,
                             TaskState.VERDICT_PASSED)

  task_result = api.tast_results.get_results(
      temp_dir, 'reven-vmtest-cq.tast_vm.tast_vm_default_shard_5_of_5', '1',
      ['arc.Boot'], 'gs://url')
  results, test_cases = api.tast_results.convert_results(task_result)
  api.tast_results.print_results(results.failures, False)
  api.assertions.assertEqual(test_cases[0]['name'], 'arc.Boot')
  # fake test case code.

  # tests_to_retry unittesting.
  tests, _ = api.tast_results.get_tests_to_retry(task_result)
  api.assertions.assertEqual(len(tests), 1)
  empty_task_result = ExecuteResponse.TaskResult(
      name=task_result.name,
      state=TaskState(verdict=TaskState.VERDICT_UNSPECIFIED))
  api.tast_results.get_tests_to_retry(empty_task_result)

  api.assertions.assertEqual(len(results.failures), 1)
  api.assertions.assertEqual(results.failures[0].kind, 'vm test')
  api.assertions.assertEqual(results.failures[0].fatal, True)
  api.assertions.assertEqual(results.failures[0].title, 'arc.Boot')
  task_result = api.tast_results.get_results(
      temp_dir, 'reven-vmtest-cq.tast_vm.tast_vm_default', '1',
      ['arc.Boot', 'arc.StartStop', 'some.Test', 'some.OtherTest'], 'gs://url')
  results, test_cases = api.tast_results.convert_results(task_result)
  api.assertions.assertEqual(len(results.failures), 4)
  api.assertions.assertEqual(results.failures[0].kind, 'vm test')
  api.assertions.assertEqual(results.failures[0].fatal, True)
  api.assertions.assertEqual(results.failures[0].title, 'arc.Boot')
  api.assertions.assertEqual(test_cases[1]['name'], 'arc.StartStop')
  api.assertions.assertEqual(test_cases[1]['humanReadableSummary'],
                             'Test did not run')

  passed_task_result = ExecuteResponse.TaskResult(
      name=task_result.name, state=TaskState(verdict=TaskState.VERDICT_PASSED),
      test_cases=[
          x for x in task_result.test_cases
          if x.verdict == TaskState.VERDICT_PASSED
      ])
  results, test_cases = api.tast_results.convert_results(passed_task_result)
  api.assertions.assertEqual(test_cases, [])
  api.tast_results.print_results(results.failures, False)
  tests, _ = api.tast_results.get_tests_to_retry(passed_task_result)
  api.assertions.assertEqual(tests, [])
  fishy_task_result = ExecuteResponse.TaskResult(name=task_result.name,
                                                 state=task_result.state)
  results, test_cases = api.tast_results.convert_results(fishy_task_result)
  api.assertions.assertEqual(test_cases, [])
  api.tast_results.print_results(results.failures, True)


def GenTests(api):

  def _set_build(bid, tags=None, experiments=None, swarming_tags=None,
                 ancestor_buildbucket_ids=None, properties=None):
    # tags is a dict, convert that into [StringPair].
    bb_tags = api.cros_tags.tags(**tags) if tags else []
    build_msg = api.buildbucket.ci_build_message(
        build_id=bid, tags=bb_tags, experiments=experiments, project='chromeos',
        bucket='vmtest', builder='reven-vmtest-direct-tast-vm')
    if swarming_tags:
      build_msg.infra.swarming.bot_dimensions.extend(
          api.cros_tags.tags(**swarming_tags))
    build_msg.infra.swarming.parent_run_id = 'parent-task-id1'

    if ancestor_buildbucket_ids:
      build_msg.ancestor_ids.extend(ancestor_buildbucket_ids)

    if properties:
      build_msg.input.properties.update(properties)
    return api.buildbucket.build(build_msg)

  build = api.buildbucket.ci_build_message()
  build.input.properties['buildTarget'] = {'name': 'amd64-generic'}
  yield api.test(
      'basic',
      api.buildbucket.build(build),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'gsutil-fail',
      api.buildbucket.build(build),
      api.step_data(
          'process tast output (2).gsutil download metadata/sources.jsonpb',
          retcode=1),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'resultdb-not-enabled',
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  build.critical = common_pb2.NO
  yield api.test(
      'non-critical',
      api.buildbucket.build(build),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'success-with-full-tags-for-resultdb',
      _set_build(
          bid=42, swarming_tags={
              'pool': 'ChromeOSSkylab',
              'kernel': '5.4.151-16902-g93699f4e73de',
          }, ancestor_buildbucket_ids=[123, 456], properties={
              'buildPayload': {
                  'artifactsGsPath': 'novato-snapshot/R111-15302.0.0',
              },
              'buildTarget': {
                  'name': 'amd64-generic'
              }
          }),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )
