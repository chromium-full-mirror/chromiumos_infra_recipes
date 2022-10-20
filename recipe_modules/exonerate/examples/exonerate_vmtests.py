# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exonerate',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


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
  exonerated_vm_builds, exonerated_test_names = api.exonerate.exonerate_vmtests(
      vm_builds)
  api.assertions.assertEqual(exonerated_test_names, [suite_name])
  api.assertions.assertEqual(exonerated_vm_builds[0].status, common_pb2.SUCCESS)
  api.assertions.assertNotIn(
      'VERDICT_FAILED',
      str(exonerated_vm_builds[0].output.properties['failed_test_cases']))

  # Case where the VM test is non-critical
  build.critical = common_pb2.NO
  exonerated_vm_builds, exonerated_test_names = api.exonerate.exonerate_vmtests(
      vm_builds)
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(exonerated_vm_builds[0].status, common_pb2.FAILURE)
  api.assertions.assertIn(
      'VERDICT_FAILED',
      str(exonerated_vm_builds[0].output.properties['failed_test_cases']))

  # Test empty failed_test_cases.
  build = api.exonerate.test_api.fake_vm_build()
  build.output.properties.update({'failed_test_cases': []})
  build.input.properties.update(
      {'buildTarget': json_format.MessageToDict(BuildTarget(name='betty'))})
  suite_name = 'betty.tast_vm.tast_vm_default'
  build.input.properties.update({'name': suite_name})
  vm_builds = [build]
  exonerated_vm_builds, exonerated_test_names = api.exonerate.exonerate_vmtests(
      vm_builds)
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(exonerated_vm_builds[0].status, common_pb2.FAILURE)

  api.exonerate.print_stats()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}),
      api.post_check(post_process.MustRun, 'exonerate vm tests'))
