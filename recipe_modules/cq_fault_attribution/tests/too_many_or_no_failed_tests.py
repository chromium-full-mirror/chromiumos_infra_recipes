# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import timestamp_pb2
from google.protobuf.json_format import ParseDict

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit, \
  Status
from PB.go.chromium.org.luci.resultdb.proto.v1.common import Variant
from PB.go.chromium.org.luci.resultdb.proto.v1.failure_reason import \
  FailureReason
from PB.go.chromium.org.luci.resultdb.proto.v1.test_result import TestResult, \
  TestStatus
from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution \
  import CqFaultAttributionApiProperties
from PB.recipe_modules.chromeos.cq_fault_attribution.tests.tests import \
  OutOfTestRangeProperties
from PB.test_platform.steps.execution import ExecuteResponse
from PB.test_platform.taskstate import TaskState
from RECIPE_MODULES.chromeos.cros_test_proctor.structs import MetaTestTuple
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult
from RECIPE_MODULES.recipe_engine.resultdb.common import Invocation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'cq_fault_attribution',
    'skylab_results',
]

PROPERTIES = OutOfTestRangeProperties


ORCH_SNAPSHOT_COMMIT_SHA = 'orchsnapshotcommitsha'

fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
pass_state = TaskState(verdict=TaskState.VERDICT_PASSED)
failing_test_cases = []
for i in range(201):
  failing_test_cases.append(
      ExecuteResponse.TaskResult.TestCaseResult(
          name=f'test{i}', verdict=TaskState.VERDICT_FAILED,
          human_readable_summary='missing SoftwareDeps: android_vm'))

failed_child_results = [
    ExecuteResponse.TaskResult(name='suite2', state=fail_state,
                               test_cases=(failing_test_cases))
]
passed_child_result = [
    ExecuteResponse.TaskResult(
        name='suite2', state=pass_state, test_cases=([
            ExecuteResponse.TaskResult.TestCaseResult(
                name='passed_test', verdict=TaskState.VERDICT_PASSED,
                human_readable_summary='missing SoftwareDeps: android_vm')
        ]))
]
# Mock Orchestrator snapshot
orch_snapshot_build = \
  build_pb2.Build(id=123,
                  status=Status.SUCCESS,
                  start_time=timestamp_pb2.Timestamp(seconds=1599999998),
                  end_time=timestamp_pb2.Timestamp(seconds=1599999998))
snapshot_test_results = [
    TestResult(
        name='test', variant=ParseDict({'def': {
            'build_target': 'variant'
        }}, Variant()), expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(primary_error_message='reason'))
]
snapshot_build_invocation \
  = Invocation(test_results=snapshot_test_results)


def RunSteps(api, properties):
  child_results = failed_child_results if properties.has_failed_tests else passed_child_result
  hw_test_failures = [
      SkylabResult(
          task=api.skylab_results.test_api.skylab_task(suite='suite1'),
          status=common_pb2.FAILURE, child_results=child_results),
  ]
  orch_snapshot = \
    GitilesCommit(
        host='chrome-internal.googlesource.com',
        project='chromeos/manifest-internal',
        id=ORCH_SNAPSHOT_COMMIT_SHA,
        ref='refs/heads/snapshot')
  cq_test_failure_attributes = \
    api.cq_fault_attribution.set_cq_fault_attribute_properties(
        MetaTestTuple(skylab=hw_test_failures, autotest_vm=[], tast_vm=[],
                      tast_gce=[]),
        orch_snapshot)
  api.assertions.assertEqual(
      len(cq_test_failure_attributes.test_failure_attributions),
      properties.expected_size)


def GenTests(api):
  yield api.test(
      'too-many-failed-unique-tests',
      api.properties(expected_size=0, has_failed_tests=True),
      api.properties(
          **{
              '$chromeos/cq_fault_attribution':
                  CqFaultAttributionApiProperties(enable_fault_attribution=True)
          }))
  yield api.test(
      'no-failed-tests', api.properties(expected_size=0,
                                        has_failed_tests=False),
      api.properties(
          **{
              '$chromeos/cq_fault_attribution':
                  CqFaultAttributionApiProperties(enable_fault_attribution=True)
          }))
