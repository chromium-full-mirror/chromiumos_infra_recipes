# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/resultdb',
    'recipe_engine/properties',
    'cros_resultdb',
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
          status=bb_common_pb2.FAILURE, child_results=child_results),
  ]

  _, _ = api.exonerate.exonerate_hwtests(hw_test_failures)
  api.exonerate.print_stats(property_name='exoneration_stats')
  api.cros_resultdb.apply_exonerated_exonerations(
      [api.cros_resultdb.current_invocation_id])


def GenTests(api):

  variant_json = api.json.dumps({'def': {'build_target': 'build_target_name'}})

  inv_bundle = {
      'build:123':
          api.resultdb.Invocation(test_results=[
              test_result_pb2.TestResult(
                  test_id='test2', expected=False,
                  status=test_result_pb2.FAIL, variant=json_format.Parse(
                      variant_json, common_pb2.Variant())),
              test_result_pb2.TestResult(
                  test_id='test/2', expected=False,
                  status=test_result_pb2.SKIP, variant=json_format.Parse(
                      variant_json, common_pb2.Variant())),
              test_result_pb2.TestResult(
                  test_id='test/exp', expected=True,
                  status=test_result_pb2.SKIP, variant=json_format.Parse(
                      variant_json, common_pb2.Variant())),
              test_result_pb2.TestResult(
                  test_id='arc.Boot2', expected=False,
                  status=test_result_pb2.FAIL, variant=json_format.Parse(
                      variant_json, common_pb2.Variant())),
          ]),
  }

  yield api.test(
      'rdb-not-enabled',
      api.post_process(post_process.DoesNotRun,
                       'exonerate exonerated failures'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'exonerate-not-enabled', api.buildbucket.try_build(build_id=123),
      api.post_process(post_process.DoesNotRun,
                       'exonerate exonerated failures'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'rdb-failure', api.buildbucket.try_build(build_id=123),
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}),
      api.resultdb.query(inv_bundle,
                         step_name='exonerate exonerated failures.rdb query'),
      api.step_data('exonerate exonerated failures.exonerate', retcode=1),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'default-exoneration', api.buildbucket.try_build(build_id=123),
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}),
      api.resultdb.query(inv_bundle,
                         step_name='exonerate exonerated failures.rdb query'),
      api.post_process(post_process.StepSuccess,
                       'exonerate exonerated failures'),
      api.post_process(post_process.DropExpectation))
