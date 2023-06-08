# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import re

from typing import Dict, List, Optional
from recipe_engine import post_process
from google.protobuf.json_format import ParseDict
from google.protobuf import timestamp_pb2, json_format

from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution import \
  CqFailureAttribute, FaultAttributedBuildTarget, FaultAttributionProperties, \
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
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'cq_fault_attribution',
    'looks_for_green',
    'skylab_results',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

BUILD_INVOCATION_ID_REGEX = 'build-(?P<build_id>.*)'

# Commit related consts
ORCH_SNAPSHOT_COMMIT_SHA = 'orchsnapshotcommitsha'

# Test case name consts
PASSING_IN_SNAPSHOT_AND_CQ_TEST_CASE_NAME = \
  'this.test.passed.in.the.snapshot.and.cq'
PASSING_IN_SNAPSHOT_TEST_CASE_NAME = 'this.test.passed.in.the.snapshot.only'
UNIQUE_FAILURE_TEST_CASE_NAME = \
  'this.test.failed.for.a.unique.reason.in.the.snapshot'
FLAKY_TEST_CASE_NAME = 'this.test.is.flaky'
FLAKY_FAILURE_REASON = 'flaked out for odd reasons'
EXISTING_FAILURE_TEST_CASE_NAME = \
  'this.test.failed.for.an.identical.reason.in.the.snapshot'
EXISTING_FAILURE_REASON = 'Failed for an identical, existing reason.'
SKIPPED_TEST_CASE_NAME = 'this.test.was.skipped.in.the.snapshot'
EXISTING_FAILURE_VM_TEST_CASE_NAME = \
  'this.vm.test.failed.for.an.identical.reason.in.the.snapshot'
UNIQUE_VM_FAILURE_TEST_CASE_NAME = \
  'this.vm.test.failed.for.a.unique.reason.in.the.snapshot'
PASSING_IN_SNAPSHOT_GCE_TEST_CASE_NAME = \
  'this.gce.test.passed.in.the.snapshot.only'


def get_rdb_test_result_name(invocation_id: str, test_name: str) -> str:
  return 'invocations/{}/tests/{}/results/12345'.format(invocation_id,
                                                        test_name)


def get_build_id_from_invocation(invocation_id: str) -> int:
  m = re.search(BUILD_INVOCATION_ID_REGEX, invocation_id)
  return int(m.groupdict()['build_id']) if m and m.groupdict() and 'build_id' \
                                           in m.groupdict() else 0


def get_build_target_index(items: List[FaultAttributedBuildTarget],
                           build_target: str) -> Optional[int]:
  index = None
  for i, item in enumerate(items):
    if item.build_target == build_target:
      index = i
      break
  return index


pass_state = TaskState(verdict=TaskState.VERDICT_PASSED)
fail_state = TaskState(verdict=TaskState.VERDICT_FAILED)
passing_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=PASSING_IN_SNAPSHOT_AND_CQ_TEST_CASE_NAME,
    verdict=TaskState.VERDICT_PASSED)
passed_in_snapshot_failed_in_cq_test_case = \
  ExecuteResponse.TaskResult.TestCaseResult(
    name=PASSING_IN_SNAPSHOT_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary='missing SoftwareDeps: android_vm')
unique_failure_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=UNIQUE_FAILURE_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary='missing SoftwareDeps: android_vm')
flaky_failure_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=FLAKY_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary=FLAKY_FAILURE_REASON)
existing_failure_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=EXISTING_FAILURE_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
    human_readable_summary=EXISTING_FAILURE_REASON)
skipped_test_case = ExecuteResponse.TaskResult.TestCaseResult(
    name=SKIPPED_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED)

all_passed_child_results = [
    ExecuteResponse.TaskResult(name='suite1', state=pass_state, attempt=0,
                               test_cases=[passing_test_case])
]
failed_and_skipped_child_results = [
    ExecuteResponse.TaskResult(
        name='suite2', state=fail_state, attempt=0,
        test_cases=[existing_failure_test_case, skipped_test_case])
]
mix_of_pass_fail_skipped_child_results = \
  [ExecuteResponse.TaskResult(name='suite2', state=fail_state, attempt=0,
                                                       test_cases=[
                                                           passing_test_case,
                                                           passed_in_snapshot_failed_in_cq_test_case,
                                                           unique_failure_test_case,
                                                           flaky_failure_test_case,
                                                           existing_failure_test_case,
                                                           skipped_test_case])]

brya_variant = ParseDict({'def': {'build_target': 'brya'}}, Variant())
scarlet_variant = ParseDict({'def': {'build_target': 'scarlet'}}, Variant())

# Setup snapshot builds in descending order of start time.
snapshot_build_1_invocation_id = 'build-123'
snapshot_build_1 = \
  build_pb2.Build(
      id=get_build_id_from_invocation(snapshot_build_1_invocation_id),
      status=Status.SUCCESS,
      start_time=timestamp_pb2.Timestamp(seconds=1600000000))
snapshot_build_1_invocation = Invocation(test_results=[])

snapshot_build_2_invocation_id = 'build-234'
snapshot_build_2 = \
  build_pb2.Build(
      id=get_build_id_from_invocation(snapshot_build_2_invocation_id),
      status=Status.SUCCESS,
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

snapshot_build_3_invocation_id = 'build-345'
snapshot_build_3 \
  = build_pb2.Build(
    id=get_build_id_from_invocation(snapshot_build_3_invocation_id),
    status=Status.SUCCESS,
    start_time=timestamp_pb2.Timestamp(seconds=1599999998),
    end_time=timestamp_pb2.Timestamp(seconds=1599999998))
snapshot_3_brya_build_target_test_results = [
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_3_invocation_id,
                                      FLAKY_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message=FLAKY_FAILURE_REASON)),
]
snapshot_build_3_invocation \
  = Invocation(test_results=snapshot_3_brya_build_target_test_results)

snapshot_build_4_invocation_id = 'build-456'
snapshot_build_4 \
  = build_pb2.Build(
    id=get_build_id_from_invocation(snapshot_build_4_invocation_id),
    status=Status.SUCCESS,
    start_time=timestamp_pb2.Timestamp(seconds=1599999997),
    end_time=timestamp_pb2.Timestamp(seconds=1599999997))
snapshot_4_brya_build_target_test_results = [
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_4_invocation_id,
                                      FLAKY_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message=FLAKY_FAILURE_REASON)),
    TestResult(
        name=get_rdb_test_result_name(snapshot_build_4_invocation_id,
                                      FLAKY_TEST_CASE_NAME),
        variant=brya_variant, expected=True, status=TestStatus.FAIL,
        failure_reason=FailureReason(
            primary_error_message='This failed twice')),
]
snapshot_build_4_invocation \
  = Invocation(test_results=snapshot_4_brya_build_target_test_results)

invocation_bundle: Dict[str, Invocation] = {
    snapshot_build_1_invocation_id: snapshot_build_1_invocation,
    snapshot_build_2_invocation_id: snapshot_build_2_invocation,
    snapshot_build_3_invocation_id: snapshot_build_3_invocation,
    snapshot_build_4_invocation_id: snapshot_build_4_invocation
}


def RunSteps(api):
  scarlet_build_target_task = \
    api.skylab_results.test_api.skylab_task(suite='suite1')
  scarlet_build_target_task.unit.common.build_target.name = 'scarlet'
  brya_build_target_task = \
    api.skylab_results.test_api.skylab_task(suite='suite1')
  brya_build_target_task.unit.common.build_target.name = 'brya'
  hw_tests = [
      SkylabResult(task=scarlet_build_target_task,
                   status=common_pb2.Status.FAILURE,
                   child_results=all_passed_child_results),
      SkylabResult(task=scarlet_build_target_task,
                   status=common_pb2.Status.FAILURE,
                   child_results=failed_and_skipped_child_results),
      SkylabResult(task=brya_build_target_task,
                   status=common_pb2.Status.SUCCESS,
                   child_results=all_passed_child_results),
      SkylabResult(task=brya_build_target_task,
                   status=common_pb2.Status.FAILURE,
                   child_results=mix_of_pass_fail_skipped_child_results),
  ]

  build_input = build_pb2.Build.Input()
  build_input.properties['buildTarget'] = {'name': 'brya'}
  successful_vm_build = build_pb2.Build(status=common_pb2.Status.SUCCESS,
                                        input=build_input)

  failed_vm_test_case_result1 = ExecuteResponse.TaskResult.TestCaseResult(
      name=EXISTING_FAILURE_VM_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
      human_readable_summary=EXISTING_FAILURE_REASON)
  existing_vm_failure_test_case = json_format.MessageToDict(
      failed_vm_test_case_result1)
  failed_vm_test_case_result2 = ExecuteResponse.TaskResult.TestCaseResult(
      name=UNIQUE_VM_FAILURE_TEST_CASE_NAME, verdict=TaskState.VERDICT_FAILED,
      human_readable_summary='Unique failure message')
  new_vm_failure_test_case = json_format.MessageToDict(
      failed_vm_test_case_result2)

  failed_vm_build_output = build_pb2.Build.Output()
  failed_vm_build_output.properties['failed_test_cases'] = [
      existing_vm_failure_test_case, new_vm_failure_test_case
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

  orch_snapshot = \
    GitilesCommit(
        host="chrome-internal.googlesource.com",
        project="chromeos/manifest-internal",
        id=ORCH_SNAPSHOT_COMMIT_SHA,
        ref="refs/heads/snapshot")

  fault_attributes = api.cq_fault_attribution.set_cq_fault_attribute_properties(
      MetaTestTuple(skylab=hw_tests, autotest_vm=[], tast_vm=vm_tests,
                    tast_gce=[failed_gce_build]), orch_snapshot)

  expected_snapshot_comparison_properties = \
    create_expected_snapshot(
        get_build_id_from_invocation(snapshot_build_2_invocation_id),
        1599999999)
  flakiness_comparison_snapshots = [
      create_expected_snapshot(
          get_build_id_from_invocation(snapshot_build_2_invocation_id),
          1599999999),
      create_expected_snapshot(
          get_build_id_from_invocation(snapshot_build_3_invocation_id),
          1599999998),
      create_expected_snapshot(
          get_build_id_from_invocation(snapshot_build_4_invocation_id),
          1599999997)
  ]

  fault_attributed_build_targets = fault_attributes.test_failure_attributions

  # Verify fault attributes for Brya build target.
  actual_brya_fault_attributes_target = \
    fault_attributed_build_targets[
      get_build_target_index(fault_attributed_build_targets, 'brya')
    ]

  expected_brya_new_hw_test_failure = \
    create_expected_fault_attribute_properties(
        PASSING_IN_SNAPSHOT_TEST_CASE_NAME,
        CqFailureAttribute.SUCCESS_FOUND,
        False,
        expected_snapshot_comparison_properties,
        flakiness_comparison_snapshots)
  expected_brya_unique_hw_test_failure = \
    create_expected_fault_attribute_properties(
        UNIQUE_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.DIFFERING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties,
        [])
  expected_brya_existing_hw_test_failure = \
    create_expected_fault_attribute_properties(
        EXISTING_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.MATCHING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties,
        [])
  expected_brya_flaky_hw_test_failure = \
    create_expected_fault_attribute_properties(
        FLAKY_TEST_CASE_NAME,
        CqFailureAttribute.SUCCESS_FOUND,
        True,
        expected_snapshot_comparison_properties,
        flakiness_comparison_snapshots)
  expected_brya_no_comparison_hw_test_failure = \
    create_expected_fault_attribute_properties(
        SKIPPED_TEST_CASE_NAME,
        CqFailureAttribute.NO_COMPARISON,
        False,
        expected_snapshot_comparison_properties,
        [])
  expected_brya_new_gce_test_failure = \
    create_expected_fault_attribute_properties(
        PASSING_IN_SNAPSHOT_GCE_TEST_CASE_NAME,
        CqFailureAttribute.SUCCESS_FOUND,
        False,
        expected_snapshot_comparison_properties,
        flakiness_comparison_snapshots)
  expected_brya_unique_vm_test_failure = \
    create_expected_fault_attribute_properties(
        UNIQUE_VM_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.DIFFERING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties,
        [])
  expected_brya_existing_vm_test_failure = \
    create_expected_fault_attribute_properties(
        EXISTING_FAILURE_VM_TEST_CASE_NAME,
        CqFailureAttribute.MATCHING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties,
        [])

  api.assertions.assertIn(expected_brya_new_hw_test_failure,
                          actual_brya_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(expected_brya_unique_hw_test_failure,
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

  # Verify fault attributes for Scarlet build target.
  actual_scarlet_fault_attributes_target = \
    fault_attributed_build_targets[
      get_build_target_index(fault_attributed_build_targets, 'scarlet')
    ]

  expected_scarlet_existing_failure = \
    create_expected_fault_attribute_properties(
        EXISTING_FAILURE_TEST_CASE_NAME,
        CqFailureAttribute.MATCHING_FAILURE_FOUND,
        False,
        expected_snapshot_comparison_properties,
        [])
  expected_scarlet_no_comparison_failure = \
    create_expected_fault_attribute_properties(
        SKIPPED_TEST_CASE_NAME,
        CqFailureAttribute.NO_COMPARISON,
        False,
        expected_snapshot_comparison_properties,
        [])

  api.assertions.assertIn(
      expected_scarlet_existing_failure,
      actual_scarlet_fault_attributes_target.fault_attributes)
  api.assertions.assertIn(
      expected_scarlet_no_comparison_failure,
      actual_scarlet_fault_attributes_target.fault_attributes)
  api.assertions.assertEqual(len(fault_attributed_build_targets), 2)


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results(
          builds=[snapshot_build_1],
          step_name='set fault attributes.buildbucket.search'),
      api.buildbucket.simulated_search_results(
          builds=[snapshot_build_2, snapshot_build_3, snapshot_build_4],
          step_name='set fault attributes.buildbucket.search (2)'),
      api.resultdb.query(inv_bundle=invocation_bundle,
                         step_name='set fault attributes.rdb query'),
      api.post_process(post_process.PropertiesContain,
                       'test_failure_attributions'))


def create_expected_snapshot(source_build_id, source_completed_unix_timestamp):
  expected_snapshot_comparison_properties = SnapshotProperties()
  expected_snapshot_comparison_properties.source_build_id = source_build_id
  expected_snapshot_comparison_properties.source_completed_unix_timestamp = \
    source_completed_unix_timestamp

  return expected_snapshot_comparison_properties


def create_expected_fault_attribute_properties(
    test_name, snapshot_comparison_fault_attribution, likely_flaky,
    expected_snapshot_comparison_properties, flakiness_comparison_snapshots):
  expected_fault_attribute_properties = FaultAttributionProperties()
  expected_fault_attribute_properties.test_name = test_name
  expected_fault_attribute_properties.attempt = 0
  expected_fault_attribute_properties.snapshot_comparison_fault_attribution = \
    snapshot_comparison_fault_attribution
  expected_fault_attribute_properties.likely_flaky = likely_flaky
  expected_fault_attribute_properties.comparison_snapshot.CopyFrom(
      expected_snapshot_comparison_properties)
  expected_fault_attribute_properties.flakiness_criteria_snapshots.extend(
      flakiness_comparison_snapshots)

  return expected_fault_attribute_properties
