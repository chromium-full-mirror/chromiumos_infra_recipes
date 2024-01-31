# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format
from recipe_engine import post_process

from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exonerate',
]



def RunSteps(api):
  build = api.exonerate.test_api.fake_vm_build()
  failed_test_case_result1 = ExecuteResponse.TaskResult.TestCaseResult(
      name='test1', verdict=TaskState.VERDICT_FAILED,
      human_readable_summary='something wrong here')
  failed_test_case_dict1 = json_format.MessageToDict(failed_test_case_result1)
  build.output.properties.update(
      {'failed_test_cases': [failed_test_case_dict1]})
  build.input.properties.update(
      {'buildTarget': json_format.MessageToDict(BuildTarget(name='betty'))})
  suite_name = 'betty.tast_vm.tast_vm_default'
  build.input.properties.update({'name': suite_name})
  vm_builds = [build]
  _ = api.exonerate.exonerate_vmtests(vm_builds)
  api.exonerate.auto_exoneration_analysis()


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
                       'Automated Exoneration Analysis'))
