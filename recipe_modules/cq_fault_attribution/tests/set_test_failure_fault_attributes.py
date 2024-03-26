# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import re

from typing import Dict, List, Optional, Union
from recipe_engine import post_process
from google.protobuf import timestamp_pb2, json_format

from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution import \
  CqFaultAttributionApiProperties, CqFailureAttribute, \
  FaultAttributedBuildTarget, FaultAttributionProperties, \
  SnapshotProperties
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.taskstate import TaskState
from PB.test_platform.steps.execution import ExecuteResponse
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit,\
  Status
from PB.go.chromium.org.luci.resultdb.proto.v1.test_result import TestResult, \
  TestStatus
from PB.go.chromium.org.luci.resultdb.proto.v1.failure_reason import FailureReason
from PB.go.chromium.org.luci.resultdb.proto.v1.common import Variant
from RECIPE_MODULES.recipe_engine.resultdb.common import Invocation
from RECIPE_MODULES.chromeos.cros_test_proctor.structs import MetaTestTuple
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'cq_fault_attribution',
    'looks_for_green',
    'skylab_results',
]


BUILD_INVOCATION_ID_REGEX = 'build-(?P<build_id>.*)'

# Commit related consts
ORCH_SNAPSHOT_COMMIT_SHA = 'orchsnapshotcommitsha'

# Test case name consts
PASSING_IN_SNAPSHOT_AND_CQ_TEST_CASE_NAME = \
  'this.test.passed.in.the.snapshot.and.cq'
PASSING_IN_SNAPSHOT_TEST_CASE_NAME = 'this.test.passed.in.the.snapshot.only'
UNIQUE_FAILURE_TEST_CASE_NAME = \
  'this.test.failed.for.a.unique.reason.in.the.snapshot'
ALPHANUMERIC_FAILURE_TEST_CASE_NAME = \
  'this.test.failure.reason.should.be.treated.as.identical'
STATUS_FAILURE_TEST_CASE_NAME = \
  'this.test.failure.reason.should.be.treated.as.unique'
FLAKY_TEST_CASE_NAME = 'this.test.is.flaky'
FLAKY_FAILURE_REASON = 'flaked out for odd reasons'
EXISTING_FAILURE_TEST_CASE_NAME = \
  'this.test.failed.for.an.identical.reason.in.the.snapshot'
EXISTING_FAILURE_REASON = 'Failed for an identical, existing reason.'
SKIPPED_TEST_CASE_NAME = 'this.test.was.skipped.in.the.snapshot'
EXISTING_FAILURE_VM_TEST_CASE_NAME = \
  'tast.this.vm.test.failed.for.an.identical.reason.in.the.snapshot'
EXISTING_FAILURE_VM_TEST_CASE_NAME_NO_TAST_PREFIX = \
  'this.vm.test.failed.for.an.identical.reason.in.the.snapshot'
UNIQUE_VM_FAILURE_TEST_CASE_NAME = \
  'tast.this.vm.test.failed.for.a.unique.reason.in.the.snapshot'
VM_FAILURE_WITH_NO_REASON_TEST_CASE_NAME = \
  'tast.this.vm.test.failed.without.a.reason'
PASSING_IN_SNAPSHOT_GCE_TEST_CASE_NAME = \
  'tast.this.gce.test.passed.in.the.snapshot.only'
PASSED_THEN_FAILED_TEST_CASE_NAME = \
  'this.test.passed.on.first.attempt.then.failed.on.second'


def get_rdb_test_result_name(invocation_id: str, test_name: str) -> str:
  return 'invocations/{}/tests/{}/results/12345'.format(invocation_id,
                                                        test_name)


def get_build_id_from_invocation(invocation_id: str) -> int:
  m = re.search(BUILD_INVOCATION_ID_REGEX, invocation_id)
  return int(m.groupdict()['build_id']) if m and m.groupdict() and 'build_id' \
                                           in m.groupdict() else 0


def get_build_target_index(items: List[FaultAttributedBuildTarget],
                           build_target: str,
                           model: Union[str, None]) -> Optional[int]:
  index = None
  for i, item in enumerate(items):
    if item.build_target == build_target:
      if (not item.model and not model) or (model and model == item.model):
        index = i
        break
  return index


pass_state = TaskState(verdict=TaskState.VERDICT_PASSED)
fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
no_verdict_state = TaskState(verdict=TaskState.VERDICT_NO_VERDICT)
passing_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=PASSING_IN_SNAPSHOT_AND_CQ_TEST_CASE_NAME,
    verdict=TaskState.VERDICT_PASSED)
no_verdict_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name='no verdict', verdict=TaskState.VERDICT_NO_VERDICT)
passed_in_snapshot_failed_in_cq_test_case = \
  ExecuteResponse.TaskResult.TestCaseResult(
    name=PASSING_IN_SNAPSHOT_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary='missing SoftwareDeps: android_vm')
unique_failure_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=UNIQUE_FAILURE_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary='missing SoftwareDeps: android_vm')
alphanumeric_failure_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=ALPHANUMERIC_FAILURE_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary='some failure at 2023-09-06T15:57:34.502767Z on UUID F7451C0913175B8DC7DD8603C0D86B87. File /a/c/fpimages_1694011118/d'
)
status_failure_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=STATUS_FAILURE_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary='some failure code 2000')
flaky_failure_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=FLAKY_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary=FLAKY_FAILURE_REASON)
existing_failure_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=EXISTING_FAILURE_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary=EXISTING_FAILURE_REASON)
skipped_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=SKIPPED_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED)
passed_on_first_attempt_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=PASSED_THEN_FAILED_TEST_CASE_NAME, verdict=TaskState.VERDICT_PASSED)
failed_on_second_attempt_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=PASSED_THEN_FAILED_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED)

all_passed_child_results = [
    ExecuteResponse.TaskResult(name='suite1', state=pass_state, attempt=0,
                               test_cases=[passing_test_case])
]
no_verdict_child_results = [
    ExecuteResponse.TaskResult(name='suite1', state=no_verdict_state, attempt=0,
                               test_cases=[passing_test_case])
]
failed_and_skipped_child_results = [
    ExecuteResponse.TaskResult(
        name='suite2', state=fail_state, attempt=0,
        test_cases=[existing_failure_test_case, skipped_test_case])
]
passed_on_first_attempt_child_results = [
    ExecuteResponse.TaskResult(name='suite2', state=pass_state, attempt=0,
                               test_cases=[passed_on_first_attempt_test_case])
]
failed_on_second_attempt_child_results = [
    ExecuteResponse.TaskResult(name='suite2', state=fail_state, attempt=1,
                               test_cases=[failed_on_second_attempt_test_case])
]
mix_of_pass_fail_skipped_child_results = \
  [ExecuteResponse.TaskResult(name='suite2', state=fail_state, attempt=0,
                                                       test_cases=[
                                                           passing_test_case,
                                                           passed_in_snapshot_failed_in_cq_test_case,
                                                           unique_failure_test_case,
                                                           alphanumeric_failure_test_case,
                                                           status_failure_test_case,
                                                           flaky_failure_test_case,
                                                           existing_failure_test_case,
                                                           skipped_test_case,
                                                           no_verdict_test_case])]

brya_variant = json_format.ParseDict({'def': {
    'build_target': 'brya'
}}, Variant())
brya_redrix_variant = json_format.ParseDict(
    {'def': {
        'build_target': 'brya',
        'model': 'redrix'
    }}, Variant())
scarlet_variant = json_format.ParseDict({'def': {
    'build_target': 'scarlet'
}}, Variant())

# Mock Orchestrator postsubmit
output = build_pb2.Build.Output()
orch_postsubmit_build = \
  build_pb2.Build(id=456, output=output, input=build_pb2.Build.Input())

# Setup snapshot builds in descending order of start time.
snapshot_build_1_invocation_id = 'build-123'
snapshot_build_1 = \
  build_pb2.Build(
      id=get_build_id_from_invocation(snapshot_build_1_invocation_id),
      status=Status.SUCCESS,
      create_time=timestamp_pb2.Timestamp(seconds=1600000000),
      start_time=timestamp_pb2.Timestamp(seconds=1600000000))
snapshot_build_1_invocation = Invocation(test_results=[])

snapshot_build_2_invocation_id = 'build-234'
snapshot_build_2 = \
  build_pb2.Build(
      id=get_build_id_from_invocation(snapshot_build_2_invocation_id),
      status=Status.SUCCESS,
      create_time=timestamp_pb2.Timestamp(seconds=1599999999),
      start_time=timestamp_pb2.Timestamp(seconds=1599999999),
      end_time=timestamp_pb2.Timestamp(seconds=1599999999))
snapshot_2_brya_build_target_test_results = [
    TestResult(
        name=get_rdb_test_result_name(
            snapshot_build_2_invocation_id,
            PASSING_IN_SNAPSHOT_AND_CQ_TEST_CASE_NAME), variant=brya_variant,
        expected=True, status=TestStatus.PASS),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      FLAKY_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.PASS),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      PASSING_IN_SNAPSHOT_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.PASS),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      UNIQUE_FAILURE_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message='missing some other SoftwareDeps: android_vm'
        )),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      ALPHANUMERIC_FAILURE_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message='some failure at 2000-01-06T10:00:34.432123Z on UUID AB53CFI5313175B8DC7DD8343GK6B87. File /a/c/fpimages_1111111131/d'
        )),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      STATUS_FAILURE_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message='some failure code 3000')),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      EXISTING_FAILURE_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message=EXISTING_FAILURE_REASON)),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      PASSING_IN_SNAPSHOT_GCE_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.PASS),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      EXISTING_FAILURE_VM_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message=EXISTING_FAILURE_REASON)),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      UNIQUE_VM_FAILURE_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message='missing other SoftwareDeps: android_vm')),
]
snapshot_2_scarlet_build_target_test_results = [
    TestResult(
        name=get_rdb_test_result_name(
            snapshot_build_2_invocation_id,
            PASSING_IN_SNAPSHOT_AND_CQ_TEST_CASE_NAME), variant=scarlet_variant,
        expected=True, status=TestStatus.PASS),
    TestResult(name='unrecognized_rdb_test_name_format',
               variant=scarlet_variant, expected=True, status=TestStatus.PASS),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      UNIQUE_FAILURE_TEST_CASE_NAME),
        variant=scarlet_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message='missing some other SoftwareDeps: android_vm'
        )),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      EXISTING_FAILURE_TEST_CASE_NAME),
        variant=scarlet_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message=EXISTING_FAILURE_REASON)),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      SKIPPED_TEST_CASE_NAME),
        variant=scarlet_variant, expected=True, status=TestStatus.SKIP),
]
snapshot_build_2_invocation \
  = Invocation(
    test_results=snapshot_2_brya_build_target_test_results +
                 snapshot_2_scarlet_build_target_test_results)

snapshot_build_3_invocation_id = 'build-1123'
snapshot_build_3 = \
  build_pb2.Build(
      id=get_build_id_from_invocation(snapshot_build_3_invocation_id),
      status=Status.SUCCESS,
      create_time=timestamp_pb2.Timestamp(seconds=1599999998),
      start_time=timestamp_pb2.Timestamp(seconds=1599999998),
      end_time=timestamp_pb2.Timestamp(seconds=1599999998))
snapshot_3_brya_redrix_build_target_test_results = [
    TestResult(
        name=get_rdb_test_result_name(
            snapshot_build_3_invocation_id,
            PASSING_IN_SNAPSHOT_AND_CQ_TEST_CASE_NAME),
        variant=brya_redrix_variant, expected=True, status=TestStatus.FAIL)
]
snapshot_build_3_invocation \
  = Invocation(
    test_results=snapshot_3_brya_redrix_build_target_test_results)

snapshot_build_4_invocation_id = 'build-345'
snapshot_build_4 \
  = build_pb2.Build(
    id=get_build_id_from_invocation(snapshot_build_4_invocation_id),
    status=Status.SUCCESS,
    create_time=timestamp_pb2.Timestamp(seconds=1599999997),
    start_time=timestamp_pb2.Timestamp(seconds=1599999997),
    end_time=timestamp_pb2.Timestamp(seconds=1599999997))
snapshot_4_brya_build_target_test_results = [
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_4_invocation_id,
                                      FLAKY_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message=FLAKY_FAILURE_REASON)),
    # This same test exists in a newer snapshot (snapshot 2) as a passing test.
    # We create an older instance with a different outcome to validate the
    # newer one is used.
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_2_invocation_id,
                                      PASSING_IN_SNAPSHOT_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL),
]
snapshot_build_4_invocation \
  = Invocation(test_results=snapshot_4_brya_build_target_test_results)

snapshot_build_5_invocation_id = 'build-456'
snapshot_build_5 \
  = build_pb2.Build(
    id=get_build_id_from_invocation(snapshot_build_5_invocation_id),
    status=Status.SUCCESS,
    create_time=timestamp_pb2.Timestamp(seconds=1599999996),
    start_time=timestamp_pb2.Timestamp(seconds=1599999996),
    end_time=timestamp_pb2.Timestamp(seconds=1599999996))
snapshot_5_brya_build_target_test_results = [
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_5_invocation_id,
                                      FLAKY_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message=FLAKY_FAILURE_REASON)),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_5_invocation_id,
                                      FLAKY_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message='This failed twice')),
]
snapshot_build_5_invocation \
  = Invocation(test_results=snapshot_5_brya_build_target_test_results)

invocation_bundle: Dict[str, Invocation] = {
    snapshot_build_1_invocation_id: snapshot_build_1_invocation,
    snapshot_build_2_invocation_id: snapshot_build_2_invocation,
    snapshot_build_3_invocation_id: snapshot_build_3_invocation,
    snapshot_build_4_invocation_id: snapshot_build_4_invocation,
    snapshot_build_5_invocation_id: snapshot_build_5_invocation
}


def RunSteps(api):
  scarlet_build_target_task = \
    api.skylab_results.test_api.skylab_task(suite='suite1')
  scarlet_build_target_task.unit.common.build_target.name = 'scarlet'
  scarlet_dru_build_target_task = \
    api.skylab_results.test_api.skylab_task(suite='suite1')
  scarlet_dru_build_target_task.unit.common.build_target.name = 'scarlet'
  scarlet_dru_build_target_task.test.skylab_model = 'dru'
  brya_build_target_task = \
    api.skylab_results.test_api.skylab_task(suite='suite1')
  brya_build_target_task.unit.common.build_target.name = 'brya'
  brya_non_critical_build_target_task = \
    api.skylab_results.test_api.skylab_task(suite='suite1')
  brya_non_critical_build_target_task.unit.common.build_target.name = 'brya'
  brya_non_critical_build_target_task.test.common.critical.value = False
  brya_redrix_build_target_task = \
    api.skylab_results.test_api.skylab_task(suite='suite1')
  brya_redrix_build_target_task.unit.common.build_target.name = 'brya'
  brya_redrix_build_target_task.test.skylab_model = 'redrix'
  hw_tests = [
      SkylabResult(task=scarlet_build_target_task,
                   status=common_pb2.Status.FAILURE,
                   child_results=no_verdict_child_results),
      SkylabResult(task=scarlet_build_target_task,
                   status=common_pb2.Status.FAILURE,
                   child_results=failed_and_skipped_child_results),
      SkylabResult(task=scarlet_build_target_task,
                   status=common_pb2.Status.SUCCESS,
                   child_results=passed_on_first_attempt_child_results),
      SkylabResult(task=scarlet_build_target_task,
                   status=common_pb2.Status.FAILURE,
                   child_results=failed_on_second_attempt_child_results),
      # Model specific test without any model specific snapshot comparisons.
      SkylabResult(task=scarlet_dru_build_target_task,
                   status=common_pb2.Status.FAILURE,
                   child_results=failed_and_skipped_child_results),
      SkylabResult(task=brya_non_critical_build_target_task,
                   status=common_pb2.Status.SUCCESS,
                   child_results=all_passed_child_results),
      # Model specific test with a different test outcome for a pre-existing
      # test.
      SkylabResult(
          task=brya_redrix_build_target_task, status=common_pb2.Status.FAILURE,
          child_results=[
              ExecuteResponse.TaskResult(
                  name='suite2', state=fail_state, attempt=0, test_cases=[
                      ExecuteResponse.TaskResult.TestCaseResult(
                          name=PASSING_IN_SNAPSHOT_AND_CQ_TEST_CASE_NAME,
                          verdict=TaskState.VERDICT_FAILED)
                  ])
          ]),
      SkylabResult(task=brya_build_target_task,
                   status=common_pb2.Status.FAILURE,
                   child_results=mix_of_pass_fail_skipped_child_results),
  ]

  build_input = build_pb2.Build.Input()
  build_input.properties['buildTarget'] = {'name': 'brya'}
  successful_vm_build = build_pb2.Build(status=common_pb2.Status.SUCCESS,
                                        input=build_input)

  failed_vm_test_case_result1 = ExecuteResponse.TaskResult.TestCaseResult(
      name=EXISTING_FAILURE_VM_TEST_CASE_NAME_NO_TAST_PREFIX,
      verdict=TaskState.VERDICT_FAILED,
      human_readable_summary=EXISTING_FAILURE_REASON)
  existing_vm_failure_test_case = json_format.MessageToDict(
      failed_vm_test_case_result1)
  failed_vm_test_case_result2 = ExecuteResponse.TaskResult.TestCaseResult(
      name=UNIQUE_VM_FAILURE_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
      human_readable_summary='Unique failure message')
  new_vm_failure_test_case = json_format.MessageToDict(
      failed_vm_test_case_result2)
  failed_vm_test_case_result3 = ExecuteResponse.TaskResult.TestCaseResult(
      name=VM_FAILURE_WITH_NO_REASON_TEST_CASE_NAME,
      verdict=TaskState.VERDICT_FAILED)
  absent_reason_vm_failure_test_case = json_format.MessageToDict(
      failed_vm_test_case_result3)

  failed_vm_build_output = build_pb2.Build.Output()
  failed_vm_build_output.properties['failed_test_cases'] = [
      existing_vm_failure_test_case, new_vm_failure_test_case,
      absent_reason_vm_failure_test_case
  ]
  failed_vm_build = build_pb2.Build(status=common_pb2.Status.FAILURE,
                                    input=build_input,
                                    output=failed_vm_build_output)
  vm_tests = [successful_vm_build, failed_vm_build]

  failed_gce_test_case_result = ExecuteResponse.TaskResult.TestCaseResult(
      name=PASSING_IN_SNAPSHOT_GCE_TEST_CASE_NAME,
      verdict=TaskState.VERDICT_FAILED,
      human_readable_summary='Unique failure message')
  new_gce_failure_test_case = json_format.MessageToDict(
      failed_gce_test_case_result)

  failed_gce_build_output = build_pb2.Build.Output()
  failed_gce_build_output.properties['failed_test_cases'] = [
      new_gce_failure_test_case
  ]
  failed_gce_build = build_pb2.Build(status=common_pb2.Status.FAILURE,
                                     input=build_input,
                                     output=failed_gce_build_output)

  failed_gce_build_missing_failed_test_cases = \
    build_pb2.Build(status=common_pb2.Status.FAILURE,
                                     input=build_input,
                                     output=build_pb2.Build.Output())

  orch_snapshot = \
    GitilesCommit(
        host='chrome-internal.googlesource.com',
        project='chromeos/manifest-internal',
        id=ORCH_SNAPSHOT_COMMIT_SHA,
        ref='refs/heads/snapshot')

  fault_attributes = api.cq_fault_attribution.set_cq_fault_attribute_properties(
      MetaTestTuple(
          skylab=hw_tests, autotest_vm=[], tast_vm=vm_tests, tast_gce=[
              failed_gce_build, failed_gce_build_missing_failed_test_cases
          ]), orch_snapshot)

  expected_snapshot_comparison_properties = \
    create_expected_snapshot(
        get_build_id_from_invocation(snapshot_build_2_invocation_id),
        1599999999)
  compared_snapshots = [
      create_expected_snapshot(
          get_build_id_from_invocation(snapshot_build_2_invocation_id),
          1599999999),
      create_expected_snapshot(
          get_build_id_from_invocation(snapshot_build_3_invocation_id),
          1599999998),
      create_expected_snapshot(
          get_build_id_from_invocation(snapshot_build_4_invocation_id),
          1599999997),
      create_expected_snapshot(
          get_build_id_from_invocation(snapshot_build_5_invocation_id),
          1599999996)
  ]

  fault_attributed_build_targets = fault_attributes.test_failure_attributions

  # Verify fault attributes for Brya build target.
  actual_brya_fault_attributes_target = \
    fault_attributed_build_targets[
      get_build_target_index(fault_attributed_build_targets, 'brya', None)
    ]

  expected_brya_new_hw_test_failure = \
    create_expected_fault_attribute_properties(
        PASSING_IN_SNAPSHOT_TEST_CASE_NAME,
        CqFailureAttribute.SUCCESS_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_brya_unique_hw_test_failure = \
    create_expected_fault_attribute_properties(
        UNIQUE_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.DIFFERING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_brya_alphanumeric_hw_test_failure = \
    create_expected_fault_attribute_properties(
        ALPHANUMERIC_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.MATCHING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_brya_status_hw_test_failure = \
    create_expected_fault_attribute_properties(
        STATUS_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.DIFFERING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_brya_existing_hw_test_failure = \
    create_expected_fault_attribute_properties(
        EXISTING_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.MATCHING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_brya_flaky_hw_test_failure = \
    create_expected_fault_attribute_properties(
        FLAKY_TEST_CASE_NAME,
        CqFailureAttribute.SUCCESS_FOUND,
        True,
        expected_snapshot_comparison_properties)
  expected_brya_no_comparison_hw_test_failure = \
    create_expected_fault_attribute_properties(
        SKIPPED_TEST_CASE_NAME,
        CqFailureAttribute.NO_COMPARISON,
        False,
        None)
  expected_brya_new_gce_test_failure = \
    create_expected_fault_attribute_properties(
        PASSING_IN_SNAPSHOT_GCE_TEST_CASE_NAME,
        CqFailureAttribute.SUCCESS_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_brya_unique_vm_test_failure = \
    create_expected_fault_attribute_properties(
        UNIQUE_VM_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.DIFFERING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_brya_existing_vm_test_failure = \
    create_expected_fault_attribute_properties(
        EXISTING_FAILURE_VM_TEST_CASE_NAME,
        CqFailureAttribute.MATCHING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_brya_absent_reason_vm_test_failure = \
    create_expected_fault_attribute_properties(
        VM_FAILURE_WITH_NO_REASON_TEST_CASE_NAME,
        CqFailureAttribute.NO_COMPARISON,
        False,
        None)

  api.assertions.assertIn(expected_brya_new_hw_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_unique_hw_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_alphanumeric_hw_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_status_hw_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_existing_hw_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_flaky_hw_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_no_comparison_hw_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_new_gce_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_unique_vm_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_existing_vm_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_absent_reason_vm_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertEqual(
      len(actual_brya_fault_attributes_target.fault_attributes), 11)

  # Verify fault attributes for Scarlet build target.
  actual_scarlet_fault_attributes_target = \
    fault_attributed_build_targets[
      get_build_target_index(fault_attributed_build_targets, 'scarlet', None)
    ]

  expected_scarlet_existing_failure = \
    create_expected_fault_attribute_properties(
        EXISTING_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.MATCHING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_scarlet_no_comparison_failure = \
    create_expected_fault_attribute_properties(
        SKIPPED_TEST_CASE_NAME,
        CqFailureAttribute.NO_COMPARISON,
        False,
        None)

  api.assertions.assertIn(
      expected_scarlet_existing_failure,
      actual_scarlet_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(
      expected_scarlet_no_comparison_failure,
      actual_scarlet_fault_attributes_target.fault_attributes)
  api.assertions.assertEqual(
      len(actual_scarlet_fault_attributes_target.fault_attributes), 2)

  # Verify fault attributes for Scarlet.Dru build target.
  actual_scarlet_dru_fault_attributes_target = \
    fault_attributed_build_targets[
      get_build_target_index(fault_attributed_build_targets, 'scarlet', 'dru')
    ]

  expected_scarlet_dru_existing_failure = \
    create_expected_fault_attribute_properties(
        EXISTING_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.MATCHING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties)
  expected_scarlet_dru_existing_failure.diff_model_used = True

  expected_scarlet_dru_no_comparison_failure = \
    create_expected_fault_attribute_properties(
        SKIPPED_TEST_CASE_NAME,
        CqFailureAttribute.NO_COMPARISON,
        False,
        None)

  api.assertions.assertIn(
      expected_scarlet_dru_existing_failure,
      actual_scarlet_dru_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(
      expected_scarlet_dru_no_comparison_failure,
      actual_scarlet_dru_fault_attributes_target.fault_attributes)
  api.assertions.assertEqual(
      len(actual_scarlet_dru_fault_attributes_target.fault_attributes), 2)

  # Verify fault attributes for Brya.Redrix build target.
  expected_snapshot_comparison_properties = \
    create_expected_snapshot(
        get_build_id_from_invocation(snapshot_build_3_invocation_id),
        1599999998)
  actual_brya_redrix_fault_attributes_target = \
    fault_attributed_build_targets[
      get_build_target_index(fault_attributed_build_targets, 'brya', 'redrix')
    ]

  expected_brya_redrix_new_hw_test_failure = \
    create_expected_fault_attribute_properties(
        PASSING_IN_SNAPSHOT_AND_CQ_TEST_CASE_NAME,
        CqFailureAttribute.MATCHING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties)

  api.assertions.assertIn(
      expected_brya_redrix_new_hw_test_failure,
      actual_brya_redrix_fault_attributes_target.fault_attributes)
  api.assertions.assertEqual(
      len(actual_brya_redrix_fault_attributes_target.fault_attributes), 1)

  api.assertions.assertEqual(len(fault_attributed_build_targets), 4)

  for compared_snapshot in compared_snapshots:
    api.assertions.assertIn(compared_snapshot,
                            fault_attributes.compared_snapshots)

  api.assertions.assertEqual(
      len(compared_snapshots), len(fault_attributes.compared_snapshots))


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cq_fault_attribution':
                  CqFaultAttributionApiProperties(enable_fault_attribution=True)
          }),
      api.buildbucket.simulated_search_results(
          builds=[orch_postsubmit_build],
          step_name='set fault attributes.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[snapshot_build_1],
          step_name='set fault attributes.buildbucket.search (2)'),
      api.buildbucket.simulated_search_results(
          builds=[
              snapshot_build_2, snapshot_build_3, snapshot_build_4,
              snapshot_build_5
          ], step_name='set fault attributes.buildbucket.search (3)'),
      api.resultdb.query(inv_bundle=invocation_bundle,
                         step_name='set fault attributes.rdb query'),
      api.post_process(post_process.PropertiesContain, 'cq_fault_attributions'))


def create_expected_snapshot(source_build_id, source_completed_unix_timestamp):
  expected_snapshot_comparison_properties = SnapshotProperties()
  expected_snapshot_comparison_properties.source_build_id = source_build_id
  expected_snapshot_comparison_properties.source_completed_unix_timestamp = \
    source_completed_unix_timestamp
  expected_snapshot_comparison_properties.source_started_unix_timestamp = \
    source_completed_unix_timestamp

  return expected_snapshot_comparison_properties


def create_expected_fault_attribute_properties(
    test_name, snapshot_comparison_fault_attribution, likely_flaky,
    expected_snapshot_comparison_properties):
  expected_fault_attribute_properties = FaultAttributionProperties()
  expected_fault_attribute_properties.test_name = test_name
  expected_fault_attribute_properties.attempt = 0
  expected_fault_attribute_properties.snapshot_comparison_fault_attribution = \
    snapshot_comparison_fault_attribution
  expected_fault_attribute_properties.likely_flaky = likely_flaky
  if expected_snapshot_comparison_properties:
    expected_fault_attribute_properties.comparison_snapshot.CopyFrom(
        expected_snapshot_comparison_properties)

  return expected_fault_attribute_properties
