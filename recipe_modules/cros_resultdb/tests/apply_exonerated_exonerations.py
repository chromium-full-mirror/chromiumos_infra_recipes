# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from google.protobuf import json_format

from PB.chromiumos.common import BuildTarget
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
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  build = api.exonerate.test_api.fake_vm_build()
  failed_test_case_result1 = ExecuteResponse.TaskResult.TestCaseResult(
      name='arc.Boot', verdict=TaskState.VERDICT_FAILED,
      human_readable_summary='something wrong here')
  failed_test_case_dict1 = json_format.MessageToDict(failed_test_case_result1)
  failed_test_case_result2 = ExecuteResponse.TaskResult.TestCaseResult(
      name='test2', verdict=TaskState.VERDICT_FAILED,
      human_readable_summary='something also wrong here')
  failed_test_case_dict2 = json_format.MessageToDict(failed_test_case_result2)
  build.output.properties.update(
      {'failed_test_cases': [failed_test_case_dict1, failed_test_case_dict2]})
  build.input.properties.update(
      {'buildTarget': json_format.MessageToDict(BuildTarget(name='betty'))})
  suite_name = 'betty.tast_vm.tast_vm_default'
  build.input.properties.update({'name': suite_name})
  vm_builds = [build]
  _ = api.exonerate.exonerate_vmtests(vm_builds)
  api.exonerate.print_stats()
  api.cros_resultdb.apply_exonerated_exonerations(
      [api.cros_resultdb.current_invocation_id])


def GenTests(api):

  variant_json = api.json.dumps({'def': {'build_target': 'betty'}})

  inv_bundle = {
      'build:123':
          api.resultdb.Invocation(test_results=[
              test_result_pb2.TestResult(
                  test_id='arc.Boot', expected=False,
                  status=test_result_pb2.FAIL, variant=json_format.Parse(
                      variant_json, common_pb2.Variant())),
              test_result_pb2.TestResult(
                  test_id='test/2', expected=False,
                  status=test_result_pb2.SKIP, variant=json_format.Parse(
                      variant_json, common_pb2.Variant())),
          ]),
  }

  yield api.test(
      'not-enabled',
      api.post_process(
          post_process.DoesNotRun,
          'exonerate ResultDB results.exonerate non-critical failures'),
  )

  yield api.test(
      'rdb-failure',
      api.buildbucket.try_build(build_id=123),
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}),
      api.resultdb.query(inv_bundle, step_name='rdb query'),
      api.step_data('exonerate exonerated failures', retcode=1),
  )

  yield api.test(
      'default-exoneration',
      api.buildbucket.try_build(build_id=123),
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}),
      api.resultdb.query(inv_bundle, step_name='rdb query'),
      api.post_process(post_process.StepSuccess,
                       'exonerate exonerated failures'),
  )
