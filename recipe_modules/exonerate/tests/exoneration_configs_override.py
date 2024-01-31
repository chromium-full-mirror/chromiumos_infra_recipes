# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from google.protobuf import json_format

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.chromiumos.test_disablement import TestDisablement
from PB.chromiumos.test_disablement import TestDisablementCfg
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

DEPS = [
    'depot_tools/gitiles',
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exonerate',
    'skylab_results',
]



def RunSteps(api):
  override_configs = {
      'fake.test': ['target_2'],
      'anotherFake.test': ['target_2']
  }

  # VM test result.
  test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name='fake.test', verdict=TaskState.VERDICT_FAILED)
  vm_build = build_pb2.Build(
      id=123,
      builder=builder_common_pb2.BuilderID(builder='something-direct-vm'),
      status='FAILURE')
  vm_build.output.properties.update(
      {'failed_test_cases': [json_format.MessageToDict(test_case_result)]})
  vm_build.input.properties.update(
      {'buildTarget': json_format.MessageToDict(BuildTarget(name='target_2'))})

  # Assert exonerable with override configs but not with the default configs.
  api.assertions.assertFalse(
      api.exonerate.is_vm_test_build_exonerable(vm_build))
  api.assertions.assertTrue(
      api.exonerate.is_vm_test_build_exonerable(vm_build, override_configs))

  # HW test result.
  hw_result = api.skylab_results.test_api.skylab_result(
      task=api.skylab_results.test_api.skylab_task(suite='suite1'),
      status='FAILURE', child_results=[
          ExecuteResponse.TaskResult(
              name='suite1', state=TaskState(verdict=TaskState.VERDICT_FAILED),
              test_cases=[
                  ExecuteResponse.TaskResult.TestCaseResult(
                      name='anotherFake.test', verdict=TaskState.VERDICT_FAILED)
              ]),
      ])

  # Assert exonerable with default configs but not with the override configs.
  api.assertions.assertTrue(api.exonerate.is_hw_result_exonerable(hw_result))
  api.assertions.assertFalse(
      api.exonerate.is_hw_result_exonerable(hw_result, override_configs))


def GenTests(api):
  # Default exoneration configs.
  exoneration_cfg = TestDisablementCfg(disablements=[
      TestDisablement(
          name='fake.test', bug_ids=['123456'], dut_criteria=[
              TestDisablement.FilterCriterion(key='build_target',
                                              values=['target'])
          ]),
      TestDisablement(name='anotherFake.test', bug_ids=['123456']),
  ])
  yield api.test(
      'basic',
      api.properties(
          **
          {'$chromeos/exonerate': ExonerateProperties(
              enable_exoneration=True)}),
      api.step_data(
          'fetch HEAD:test/exoneration/generated/test_exoneration.binaryproto',
          api.gitiles.make_encoded_file_from_bytes(
              exoneration_cfg.SerializeToString())),
      api.post_process(post_process.DropExpectation),
  )
