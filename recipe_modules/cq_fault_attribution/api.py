# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import re
from typing import List, Dict, Tuple
from collections import defaultdict
from recipe_engine import recipe_api
from google.protobuf import timestamp_pb2, json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit, \
  Status, StringPair, TimeRange, Trinary
from PB.go.chromium.org.luci.buildbucket.proto.builder_common import BuilderID
from PB.go.chromium.org.luci.resultdb.proto.v1.test_result import TestResult, \
  TestStatus
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import \
  LooksForGreenStatus
from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution \
  import CqFailureAttribute, CqTestFailureFaultAttributionStats, \
  FaultAttributedBuildTarget, FaultAttributionProperties, SnapshotProperties
from PB.test_platform.taskstate import TaskState
from RECIPE_MODULES.recipe_engine.resultdb.common import Invocation
from RECIPE_MODULES.chromeos.cros_test_proctor.structs import MetaTestTuple
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult

TEST_ID_REGEX = 'invocations/.*/tests/(?P<test_id>.*)/results/'
PREDICATE_PROJECT = 'chromeos'
PREDICATE_BUILDER = 'snapshot-orchestrator'
PREDICATE_BUCKET = 'postsubmit'
PREDICATE_BUILDER_ID = BuilderID(project=PREDICATE_PROJECT,
                                 bucket=PREDICATE_BUCKET,
                                 builder=PREDICATE_BUILDER)
VERDICTS_REQUIRING_FAULT_ATTRIBUTION = \
  [TaskState.VERDICT_FAILED, TaskState.VERDICT_UNSPECIFIED]
# Retrict snapshot retrieval to the last 4 hours (snapshot builds are
# kicked off every 30 mins)
SNAPSHOT_RETRIEVAL_LIMIT = 8
# Threshold used when marking a test as potentially flaky
FLAKINESS_THRESHOLD = 2


class CqFailureAttributionApi(recipe_api.RecipeApi):
  """A module for ascribing build and test failure attributes based on
    snapshot build comparisons."""

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self._cq_test_failure_attributes = CqTestFailureFaultAttributionStats()
    # Map of build targets to a list of fault attributed tests under the
    # target
    self._build_target_to_test_fault_attributes: Dict[
        str, List[FaultAttributionProperties]] = defaultdict(list)
    # Map of (invocation_id, test_id, build_target) to a list of test_result(s)
    self._invocation_properties_to_test_result_matrix: Dict[Tuple[
        str, str, str], List[TestResult]] = defaultdict(list)
    # Map of (build_target, test_id, failure_reason) to total occurrence count
    self._invocation_properties_to_failure_reason_count_matrix: Dict[Tuple[
        str, str, str], int] = defaultdict(int)

  @property
  def cq_test_failure_attributes(self) -> CqTestFailureFaultAttributionStats:
    """Returns determined failure attributes"""
    return self._cq_test_failure_attributes

  def set_cq_fault_attribute_properties(
      self, test_results: MetaTestTuple,
      orch_snapshot: GitilesCommit) -> CqTestFailureFaultAttributionStats:
    """Compares test failures between a snapshot and CQ build, and assigns
      failure attributes and a flakiness status to each failure if a comparison
      snapshot is found. Sets and returns failure attributes.

      Args:
        test_results: HW and VM test results.
        orch_snapshot: The manifest snapshot at the orchestrator level.
      """
    with self.m.step.nest('set fault attributes'):
      # Comparison snapshots ordered in descending order of start_time
      comparison_snapshots = self._get_comparison_snapshots(orch_snapshot)
      if not comparison_snapshots:
        # No snapshots available for comparison. Skip fault attribution.
        return self.cq_test_failure_attributes
      fault_attributed_build_targets = self._get_cq_fault_attributes(
          test_results, comparison_snapshots)

      if fault_attributed_build_targets:
        self._cq_test_failure_attributes.test_failure_attributions.extend(
            fault_attributed_build_targets)
        self.m.easy.set_properties_step(
            test_failure_attributions=self._cq_test_failure_attributes)

      return self.cq_test_failure_attributes

  def _get_cq_fault_attributes(
      self, test_results: MetaTestTuple,
      comparison_snapshots: List[build_pb2.Build]
  ) -> List[FaultAttributedBuildTarget]:
    """Returns fault attributed test failures.

      Args:
        test_results: HW and VM test results.
        comparison_snapshots: Snapshots retrieved to be used for
          comparison.
      """
    # Map of invocation IDs to invocations from snapshot builds that contain
    # at least one test result.
    invocation_id_to_invocation = dict(
        filter(lambda invocation_items: invocation_items[1].test_results,
               self._retrieve_rdb_test_results(comparison_snapshots).items()))

    for comparison_snapshot in comparison_snapshots:
      invocation_id = self._get_build_invocation_id(comparison_snapshot.id)
      if invocation_id in invocation_id_to_invocation:
        # The invocation produced test results, so we can use it to assign
        # fault attributes.
        self._set_comparison_matrices(invocation_id_to_invocation)
        comparison_snapshot_properties = self._get_snapshot_properties_object(
            comparison_snapshot)
        flakiness_criteria_snapshot_properties = list(
            map(self._get_snapshot_properties_object, comparison_snapshots))
        with self.m.step.nest('set hw test fault attributes'):
          self._set_hwtest_fault_attributes(
              test_results.skylab, invocation_id,
              comparison_snapshot_properties,
              flakiness_criteria_snapshot_properties)
        with self.m.step.nest('set vm & gce test fault attributes'):
          self._set_vm_gce_test_fault_attributes(
              test_results.tast_vm + test_results.tast_gce, invocation_id,
              comparison_snapshot_properties,
              flakiness_criteria_snapshot_properties)
        break

    fault_attributed_build_targets = []
    for k, v in self._build_target_to_test_fault_attributes.items():
      fault_attributed_build_target = FaultAttributedBuildTarget()
      fault_attributed_build_target.build_target = k
      fault_attributed_build_target.fault_attributes.extend(v)
      fault_attributed_build_targets.append(fault_attributed_build_target)

    return fault_attributed_build_targets

  def _set_vm_gce_test_fault_attributes(
      self, tests: List[build_pb2.Build], snapshot_build_invocation_id: str,
      comparison_snapshot_properties: SnapshotProperties,
      flakiness_criteria_snapshot_properties: List[SnapshotProperties]):
    """ Creates and sets fault attribution properties for a vm and gce tests and
      appends the fault attribution instance to the fault attribute list for the
      corresponding build target.

      Args:
        tests: The relevant tests (Builds) to set fault attributes for.
        snapshot_build_invocation_id: The invocation ID of the snapshot build
          to be used for fault attribution comparisons.
        comparison_snapshot_properties: Properties of the snapshot used for
        flakiness_criteria_snapshot_properties: Properties of the snapshots used
        for determining flakiness criteria.
      """
    for build in tests:
      if build.critical == Trinary.NO or build.status == Status.SUCCESS:
        continue
      build_target = self.m.cros_infra_config.get_build_target_name(build)
      prop_struct = build.output.properties['failed_test_cases']
      test_failures = json_format.MessageToDict(prop_struct)
      for test_case in test_failures:
        test_id = test_case['name']
        failure_reason = test_case['humanReadableSummary']
        self._set_fault_attribution_properties(
            build_target, test_id, failure_reason, snapshot_build_invocation_id,
            comparison_snapshot_properties,
            flakiness_criteria_snapshot_properties)

  def _set_hwtest_fault_attributes(
      self, hw_test_results: SkylabResult, snapshot_build_invocation_id: str,
      comparison_snapshot_properties: SnapshotProperties,
      flakiness_criteria_snapshot_properties: List[SnapshotProperties]):
    """ Creates and sets fault attribution properties for a HW test case and
      appends the fault attribution instance to the fault attribute list for the
      corresponding build target.

      Args:
        hw_test_results: All HW test results for the given build run.
        snapshot_build_invocation_id: The invocation ID of the snapshot build
          to be used for fault attribution comparisons.
        comparison_snapshot_properties: Properties of the snapshot used for
        flakiness_criteria_snapshot_properties: Properties of the snapshots used
        for determining flakiness criteria.
      """
    for skylab_res in hw_test_results:
      if not skylab_res.task.test.common.critical.value \
          or skylab_res.status == Status.SUCCESS:
        continue
      build_target = skylab_res.task.unit.common.build_target.name
      for child_result in skylab_res.child_results:
        if child_result.state.verdict not in \
            VERDICTS_REQUIRING_FAULT_ATTRIBUTION:
          continue
        # Test shard is not successful, check individual test cases.
        for test_case in child_result.test_cases:
          if test_case.verdict not in VERDICTS_REQUIRING_FAULT_ATTRIBUTION:
            continue
          # test_case.name here is analogous to the test_id substring in
          # the rdb test_result name.
          test_id = test_case.name
          attempt = child_result.attempt
          failure_reason = test_case.human_readable_summary
          self._set_fault_attribution_properties(
              build_target, test_id, failure_reason,
              snapshot_build_invocation_id, comparison_snapshot_properties,
              flakiness_criteria_snapshot_properties, attempt)

  def _set_fault_attribution_properties(
      self, build_target: str, test_id: str, failure_reason: str,
      snapshot_build_invocation_id: str,
      comparison_snapshot_properties: SnapshotProperties,
      flakiness_criteria_snapshot_properties: List[SnapshotProperties],
      attempt=0):
    """ Makes the calls to set the fault attribution property for the test case,
    under the build target, and also makes the call to set flakiness likelihood
    if necessary.

    Args:
      build_target: the build target this test ran for.
      test_id: The name of the test.
      failure_reason: The reason why the test failed.
      snapshot_build_invocation_id: The invocation ID of the snapshot build
          to be used for fault attribution comparisons.
      comparison_snapshot_properties: Properties of the snapshot used for
      flakiness_criteria_snapshot_properties: Properties of the snapshots used
        for determining flakiness criteria.
      attempt: The attempt number of this test.
    """
    test_fault_attribute = FaultAttributionProperties()
    test_fault_attribute.test_name = test_id
    test_fault_attribute.attempt = attempt
    test_fault_attribute.comparison_snapshot.CopyFrom(
        comparison_snapshot_properties)
    matrix_index = (snapshot_build_invocation_id, test_id, build_target)
    snapshot_test_results = \
      self._invocation_properties_to_test_result_matrix.get(
          matrix_index, [])
    self._set_test_case_failure_fault_attribution(failure_reason,
                                                  test_fault_attribute,
                                                  snapshot_test_results)
    if test_fault_attribute.snapshot_comparison_fault_attribution == \
        CqFailureAttribute.SUCCESS_FOUND:
      # This is classified as a new test failure. Determine and set
      # flakiness.
      self._set_test_case_failure_fault_attribution_flakiness(
          test_fault_attribute, failure_reason, build_target, test_id)
      test_fault_attribute.flakiness_criteria_snapshots.extend(
          flakiness_criteria_snapshot_properties)

    self._build_target_to_test_fault_attributes[build_target].append(
        test_fault_attribute)

  def _set_test_case_failure_fault_attribution_flakiness(
      self, test_fault_attribute: FaultAttributionProperties,
      failure_reason: str, build_target: str, test_id: str):
    """Sets the 'likely_flaky' property of the test_fault_attribute based
      on the number of failures present on a test case for the same failure
      reason.

      Args:
        test_fault_attribute: The fault attribute instance to set flakiness
          status for.
        failure_reason: The reason this test failed.
        build_target: The build target that this test case failure occurred
          on.
        test_id: The name of the test e.g. tast.critical-system
      """
    matrix_index = (build_target, test_id, failure_reason)
    likely_flaky =\
      self._invocation_properties_to_failure_reason_count_matrix.get(
        matrix_index, 0) >= FLAKINESS_THRESHOLD
    test_fault_attribute.likely_flaky = likely_flaky

  def _set_test_case_failure_fault_attribution(
      self, failure_reason: str,
      test_fault_attribute: FaultAttributionProperties,
      snapshot_test_results: List[TestResult]):
    """Sets the snapshot_comparison_fault_attribution property for a CQ
      hwtest based on the given snapshot test results."""
    if snapshot_test_results:
      if any(snapshot_test_result.status == TestStatus.PASS
             for snapshot_test_result in snapshot_test_results):
        test_fault_attribute.snapshot_comparison_fault_attribution = CqFailureAttribute.SUCCESS_FOUND
      elif all(snapshot_test_result.status == TestStatus.FAIL
               for snapshot_test_result in snapshot_test_results):
        if any(snapshot_test_result.failure_reason.primary_error_message ==
               failure_reason
               for snapshot_test_result in snapshot_test_results):
          # All attempts failed, and at least one of the failure reasons
          # of the snapshot attempts matches the failure reason
          # (human_readable_summary) of the CQ test.
          test_fault_attribute.snapshot_comparison_fault_attribution = CqFailureAttribute.MATCHING_FAILURE_FOUND
        else:
          # All attempts failed, but none of the failure reasons
          # of the snapshot attempts matches the failure reason
          # (human_readable_summary) of the CQ test.
          test_fault_attribute.snapshot_comparison_fault_attribution = CqFailureAttribute.DIFFERING_FAILURE_FOUND
      else:
        test_fault_attribute.snapshot_comparison_fault_attribution = CqFailureAttribute.NO_COMPARISON
    else:
      test_fault_attribute.snapshot_comparison_fault_attribution = CqFailureAttribute.NO_COMPARISON

  def _get_comparison_snapshots(
      self, orch_snapshot: GitilesCommit) -> List[build_pb2.Build]:
    """Returns at most <SNAPSHOT_RETRIEVAL_LIMIT> snapshot builds
      ordered by start_time in descending order."""
    fields = frozenset({'id', 'start_time', 'end_time', 'status'})

    if self.m.looks_for_green.stats.status \
        == LooksForGreenStatus.STATUS_RAN_OLDER:
      # LFG picked a different snapshot from the orchestrator. Use that.
      source_snapshot_build_commit_sha = \
        self.m.looks_for_green.stats.suggested.snap_commit_sha
    else:
      source_snapshot_build_commit_sha = orch_snapshot.id

    tagValue = 'commit/gitiles/{}/{}/+/{}'.format(
        orch_snapshot.host, orch_snapshot.project,
        source_snapshot_build_commit_sha)
    predicate_for_snapshot_build_retrieval = builds_service_pb2.BuildPredicate(
        builder=PREDICATE_BUILDER_ID)
    predicate_for_snapshot_build_retrieval.tags.append(
        StringPair(key='buildset', value=tagValue))
    retrieved_source_snapshot_build = self.m.buildbucket.search(
        [predicate_for_snapshot_build_retrieval], limit=1, fields=fields,
        timeout=60)

    # retrieved_source_snapshot_build may not be defined if we are using the
    # orchestrator snapshot and the build for them manifest snapshot has not
    # kicked off yet.
    upper_bound_build_for_search = retrieved_source_snapshot_build[
        0] if retrieved_source_snapshot_build else self.m.buildbucket.build

    # Retrieve snapshots that are older than the upper bound build.
    predicate_for_previous_snapshot_builds = builds_service_pb2.BuildPredicate(
        builder=PREDICATE_BUILDER_ID,
        create_time=TimeRange(
            end_time=timestamp_pb2.Timestamp(
                # +1 to make this inclusive of the upper bound build
                seconds=upper_bound_build_for_search.create_time.ToSeconds() \
                        + 1
            )))
    previous_snapshot_builds = self.m.buildbucket.search(
        [predicate_for_previous_snapshot_builds],
        limit=SNAPSHOT_RETRIEVAL_LIMIT, fields=fields, timeout=60)

    completed_snapshot_builds = list(
        filter(self._is_build_terminal_with_pass_or_fail,
               previous_snapshot_builds))
    ordered_completed_snapshot_builds = sorted(
        completed_snapshot_builds, key=(lambda build: build.start_time.seconds),
        reverse=True)

    return ordered_completed_snapshot_builds

  def _retrieve_rdb_test_results(
      self, builds: List[build_pb2.Build]) -> Dict[str, Invocation]:
    """Retrieves test results from ResultDB for the given list of builds."""
    fields = ['failureReason', 'status', 'variant']
    invocation_ids = list(
        map(lambda build: self._get_build_invocation_id(build.id), builds))

    return self.m.resultdb.query(inv_ids=invocation_ids, limit=0,
                                 tr_fields=fields)

  def _set_comparison_matrices(self,
                               invocation_id_to_invocation: Dict[str,
                                                                 Invocation]):
    """Sets the _invocation_properties_to_test_result_matrix and
      _invocation_properties_to_failure_reason_count_matrix matrices. Multiple
      attempts for the same test on the same build target are treated as unique
      entries, as they have unique invocation IDs. """
    for invocation_id, invocation in invocation_id_to_invocation.items():
      for test_result in invocation.test_results:
        test_id = self._get_test_id_from_rdb_test_name(test_result.name)
        if not test_id:
          # Test name wasn't in the expected format. Skipping.
          continue
        build_target = getattr(test_result.variant, 'def')['build_target']
        self._invocation_properties_to_test_result_matrix[(
            invocation_id, test_id, build_target)].append(test_result)

        failure_reason = test_result.failure_reason.primary_error_message
        self._invocation_properties_to_failure_reason_count_matrix[(
            build_target, test_id, failure_reason)] += 1

  def _get_build_invocation_id(self, build_id: int) -> str:
    return 'build-{}'.format(build_id)

  def _is_build_terminal_with_pass_or_fail(self,
                                           build: build_pb2.Build) -> bool:
    return (build.status == Status.SUCCESS or build.status == Status.FAILURE or
            build.status == Status.INFRA_FAILURE)

  def _get_test_id_from_rdb_test_name(self, rdb_test_name: str) -> str:
    """Returns the test_id from a test_result name from rdb. rdb test names
      are of the format:
      "invocations/{INVOCATION_ID}/tests/{TEST_ID}/results/{RESULT_ID}". """
    m = re.search(TEST_ID_REGEX, rdb_test_name)
    if not m:
      return ''
    subgroup_dict = m.groupdict()
    return subgroup_dict['test_id'] if 'test_id' in subgroup_dict else ''

  def _get_snapshot_properties_object(
      self, comparison_snapshot: build_pb2.Build) -> SnapshotProperties:
    comparison_snapshot_properties = SnapshotProperties()
    comparison_snapshot_properties.source_build_id = comparison_snapshot.id
    comparison_snapshot_properties.source_snapshot_sha = \
      comparison_snapshot.input.gitiles_commit.id
    comparison_snapshot_properties.source_completed_unix_timestamp = \
      comparison_snapshot.end_time.seconds

    return comparison_snapshot_properties
