# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exonerate',
]



def RunSteps(api):
  build = build_pb2.Build(
      id=123,
      builder=builder_common_pb2.BuilderID(builder='something-direct-vm'))
  test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name='arc.Boot', verdict=TaskState.VERDICT_FAILED)
  test_case_dict = json_format.MessageToDict(test_case_result)
  build.output.properties.update({'failed_test_cases': [test_case_dict]})
  vm_builds = [build]
  # Testing the case of disabled exoneration.
  exonerated_vm_builds, exonerated_test_names = api.exonerate.exonerate_vmtests(
      vm_builds)
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(exonerated_vm_builds[0], build)
  api.assertions.assertEqual(
      api.exonerate.is_vm_test_build_exonerable(exonerated_vm_builds[0]), False)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(**{
          '$chromeos/exonerate': ExonerateProperties(enable_exoneration=False)
      }), api.post_check(post_process.DoesNotRun, 'exonerate vm tests'))
