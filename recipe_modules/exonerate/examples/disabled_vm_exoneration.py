# -*- coding: utf-8 -*-

# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exonerate',
]

from recipe_engine import post_process
from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder as builder_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState


def RunSteps(api):
  build = build_pb2.Build(
      id=123, builder=builder_pb2.BuilderID(builder='something-direct-vm'))
  test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name='arc.Boot', verdict=TaskState.VERDICT_FAILED)
  test_case_dict = json_format.MessageToDict(test_case_result)
  build.output.properties.update({'all_test_cases': [test_case_dict]})
  vm_builds = [build]
  # Testing the case of disabled exoneration.
  exonerated_vm_builds, exonerated_test_names = api.exonerate.exonerate_vmtests(
      vm_builds)
  api.assertions.assertEqual(exonerated_test_names, [])
  api.assertions.assertEqual(exonerated_vm_builds[0], build)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(**{
          '$chromeos/exonerate': ExonerateProperties(enable_exoneration=False)
      }), api.post_check(post_process.DoesNotRun, 'exonerate vm tests'))
