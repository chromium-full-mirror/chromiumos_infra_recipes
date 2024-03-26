# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module for attributed failures based on snapshot build comparisons."""

import re

from typing import Any, Dict, List, Set, Tuple
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
  import CqFaultAttributionApiProperties, CqFailureAttribute, \
  CqTestFailureFaultAttributionStats, FaultAttributedBuildTarget, \
  FaultAttributionProperties, SnapshotProperties
from PB.test_platform.taskstate import TaskState
from RECIPE_MODULES.recipe_engine.resultdb.common import Invocation
from RECIPE_MODULES.chromeos.cros_test_proctor.structs import MetaTestTuple
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult

TEST_ID_REGEX = 'invocations/.*/tests/(?P<test_id>.*)/results/'
PREDICATE_PROJECT = 'chromeos'
PREDICATE_BUCKET = 'postsubmit'
SNAPSHOT_PREDICATE_BUILDER = 'snapshot-orchestrator'
SNAPSHOT_PREDICATE_BUILDER_ID = BuilderID(project=PREDICATE_PROJECT,
                                          bucket=PREDICATE_BUCKET,
                                          builder=SNAPSHOT_PREDICATE_BUILDER)
POSTSUBMIT_PREDICATE_BUILDER = 'postsubmit-orchestrator'
POSTSUBMIT_PREDICATE_BUILDER_ID = BuilderID(
    project=PREDICATE_PROJECT, bucket=PREDICATE_BUCKET,
    builder=POSTSUBMIT_PREDICATE_BUILDER)

VERDICTS_REQUIRING_FAULT_ATTRIBUTION = \
  [TaskState.VERDICT_FAILED, TaskState.VERDICT_UNSPECIFIED]
SUCCESS_VERDICTS = \
  [TaskState.VERDICT_PASSED_ON_RETRY, TaskState.VERDICT_PASSED]
# Restrict snapshot retrieval to the last 8 hours (snapshot builds are
# kicked off every 30 mins)
SNAPSHOT_RETRIEVAL_LIMIT = 16
POSTSUBMIT_RETRIEVAL_LIMIT = 2
# Threshold used when marking a test as potentially flaky
FLAKINESS_THRESHOLD = 2
# Maximum number of failed test IDs to query for from rdb.
# This number is derived as a result of stress testing the rdb query, which
# accounts for the highest CPU usage in this module. In combination with a
# snapshot retrieval limit of 16, this keeps CPU utilization at or below 80%.
TEST_QUERY_LIMIT = 200
EMPTY_MODEL = ''
# Regex to match against any alphanumeric strings e.g. MAC address, timestamp,
# UUID, etc, but NOT a string of numeric digits e.g. status codes.
IGNORED_FAILURE_REASON_TEXT = r'(\\|\b)([\w_\-]*[A-Za-z_]\d[\w_\-]*)(\\|\b)|(\d+:\d+[:\.]\d+)'


class CqFailureAttributionApi(recipe_api.RecipeApi):
  """A module for ascribing build and test failure attributes based on
    snapshot build comparisons."""

  def __init__(self, properties: CqFaultAttributionApiProperties,
               **kwargs: Any):
    super().__init__(**kwargs)
    # Failed VM and GCE test list, comprising dictionaries of the failed
    # "test_case" and "build".
    self._failed_vm_tests: List[Dict] = []
    # Failed HW test list, comprising dictionaries of the failed
    # "skylab_res", "child_result" and "test_case".
    self._failed_hw_tests: List[Dict] = []
    # Passed HW test set, comprising tuples of the passed
    # "test_id", "build_target" and "model".
    self._passed_hw_tests: Set[Tuple] = set()
    self._enable_fault_attribution = properties.enable_fault_attribution
    self._cq_test_failure_attributes = CqTestFailureFaultAttributionStats()
    # Map of build targets and model (may be empty) to a list of fault
    # attributed tests under the target.
    self._dut_to_test_fault_attributes: Dict[Tuple[
        str, str], List[FaultAttributionProperties]] = defaultdict(list)
    # Map of (test_id, build_target, model) to the latest completed
    # test_result(s) across the comparison snapshots.
    self._test_properties_to_latest_test_result_matrix: Dict[Tuple[
        str, str, str], List[TestResult]] = defaultdict(list)
    # Map of (test_id, build_target, model) to the snapshot containing the
    # latest results for the test.
    self._test_properties_to_latest_snapshot_matrix: Dict[Tuple[
        str, str, str], build_pb2.Build | None] = defaultdict(lambda: None)
    # Map of (build_target, model, test_id, failure_reason) to total occurrence
    # count.
    self._invocation_properties_to_failure_reason_count_matrix: Dict[Tuple[
        str, str, str, str], int] = defaultdict(int)
    # Map of (test_id, build_target, model) to the determined fault attribute.
    # This is intended to be used by the summary markdown.
    self._test_properties_to_fault_attribute: Dict[Tuple[
        str, str, str], FaultAttributionProperties] = defaultdict(lambda: None)

  @property
  def cq_test_failure_attributes(self) -> CqTestFailureFaultAttributionStats:
    """Returns determined failure attributes"""
    return self._cq_test_failure_attributes

  def set_cq_fault_attribute_properties(
      self,
      test_results: MetaTestTuple,
      orch_snapshot: GitilesCommit,
  ) -> CqTestFailureFaultAttributionStats:
    """Compares test failures between a snapshot and CQ build, and assigns
      failure attributes and a flakiness status to each failure if a comparison
      snapshot is found. Sets and returns failure attributes.

      Args:
        test_results: HW and VM test results.
        orch_snapshot: The manifest snapshot at the orchestrator level.
      """
    if not self._enable_fault_attribution:
      return self.cq_test_failure_attributes
    with self.m.step.nest(
        'set fault attributes'), self.m.failures.ignore_exceptions():

      # names of tests that failed across hw, vm and gce tests.
      failed_test_names = self._get_failed_test_names(
          test_results.skylab, test_results.tast_vm + test_results.tast_gce)
      if len(failed_test_names) > TEST_QUERY_LIMIT or \
          len(failed_test_names) == 0:
        # Too many failed tests to query for, or none.
        return self.cq_test_failure_attributes

      # Comparison snapshots ordered in descending order of start_time
      comparison_snapshots = self._get_comparison_snapshots(orch_snapshot)
      if not comparison_snapshots:
        # No snapshots available for comparison. Skip fault attribution.
        return self.cq_test_failure_attributes

      fault_attributed_build_targets = self._get_cq_fault_attributes(
          comparison_snapshots, failed_test_names)

      if fault_attributed_build_targets:
        self._cq_test_failure_attributes.test_failure_attributions.extend(
            fault_attributed_build_targets)
        self._cq_test_failure_attributes.compared_snapshots.extend(
            list(
                map(self._get_snapshot_properties_object,
                    comparison_snapshots)))
        self.m.failures.set_test_variant_to_fault_attribute(
            self._test_properties_to_fault_attribute)
        self.m.easy.set_properties_step(
            cq_fault_attributions=self._cq_test_failure_attributes)

    return self.cq_test_failure_attributes

  def _get_cq_fault_attributes(
      self, comparison_snapshots: List[build_pb2.Build],
      failed_test_names: Set[str]) -> List[FaultAttributedBuildTarget]:
    """Returns fault attributed test failures.

      Args:
        comparison_snapshots: Snapshots retrieved to be used for
          comparison.
        failed_test_names: test variant name for each test that failed.
      """
    if comparison_snapshots:
      invocation_id_to_invocation = self._retrieve_rdb_test_results(
          comparison_snapshots, failed_test_names)
      invocation_id_to_snapshot = \
        {self._get_build_invocation_id(snapshot.id): snapshot for snapshot in
         comparison_snapshots}
      self._set_comparison_matrices(invocation_id_to_invocation,
                                    invocation_id_to_snapshot)
      with self.m.step.nest('set hw test fault attributes'):
        self._set_hwtest_fault_attributes()
      with self.m.step.nest('set vm & gce test fault attributes'):
        self._set_vm_gce_test_fault_attributes()

    fault_attributed_build_targets = []
    for k, v in self._dut_to_test_fault_attributes.items():
      fault_attributed_build_target = FaultAttributedBuildTarget()
      fault_attributed_build_target.build_target = k[0]
      fault_attributed_build_target.model = k[1]
      fault_attributed_build_target.fault_attributes.extend(v)
      fault_attributed_build_targets.append(fault_attributed_build_target)

    return fault_attributed_build_targets

  def _set_vm_gce_test_fault_attributes(self):
    """ Creates and sets fault attribution properties for a vm and gce tests and
      appends the fault attribution instance to the fault attribute list for the
      corresponding build target.
      """
    for failed_vm_test in self._failed_vm_tests:
      test_case = failed_vm_test['test_case']
      build = failed_vm_test['build']
      model = EMPTY_MODEL
      build_target = self.m.cros_infra_config.get_build_target_name(build)
      test_id = self._get_vm_test_id(test_case)
      failure_reason = test_case.get('humanReadableSummary', '')
      self._set_fault_attribution_properties(build_target, model, test_id,
                                             failure_reason)

  def _set_hwtest_fault_attributes(self):
    """ Creates and sets fault attribution properties for a HW test case and
      appends the fault attribution instance to the fault attribute list for the
      corresponding build target.
      """
    for failed_hw_test in self._failed_hw_tests:
      test_case = failed_hw_test['test_case']
      child_result = failed_hw_test['child_result']
      skylab_res = failed_hw_test['skylab_res']
      test_id = test_case.name
      attempt = child_result.attempt
      failure_reason = test_case.human_readable_summary
      build_target = skylab_res.task.unit.common.build_target.name
      model = skylab_res.task.test.skylab_model or \
              EMPTY_MODEL

      # Some test variants may have actually succeeded on earlier
      # attempts but may have been retried as part of a larger shard
      # retry, e.g. when "Tast wrapped in tauto" is used. If this is the
      # case here, let's skip fault attribution on the 'failed' test variant
      # since we know it already passed earlier.
      if (test_id, build_target, model) in self._passed_hw_tests:
        continue

      self._set_fault_attribution_properties(build_target, model, test_id,
                                             failure_reason, attempt)

  def _set_fault_attribution_properties(
      self, build_target: str, model: str, test_id: str, failure_reason: str,
      attempt=0):
    """ Makes the calls to set the fault attribution property for the test case,
    under the build target, and also makes the call to set flakiness likelihood
    if necessary.

    Args:
      build_target: The build target this test ran for.
      model: The model this test ran for. May be empty.
      test_id: The name of the test.
      failure_reason: The reason why the test failed.
      attempt: The attempt number of this test.
    """
    failure_reason = re.sub(IGNORED_FAILURE_REASON_TEXT, '', failure_reason)
    test_fault_attribute = FaultAttributionProperties()
    test_fault_attribute.test_name = test_id
    test_fault_attribute.attempt = attempt
    matrix_index = (test_id, build_target, model)
    comparison_snapshot = self._test_properties_to_latest_snapshot_matrix.get(
        matrix_index)
    if model and comparison_snapshot is None:
      # If we don't have any comparisons to use when a model is specified, let's
      # attempt to find a comparison across any of the models for this target.
      matrix_index = (test_id, build_target, EMPTY_MODEL)
      comparison_snapshot = self._test_properties_to_latest_snapshot_matrix.get(
          matrix_index)
    if comparison_snapshot:
      test_fault_attribute.comparison_snapshot.CopyFrom(
          self._get_snapshot_properties_object(comparison_snapshot))
      if model not in matrix_index:
        test_fault_attribute.diff_model_used = True
    snapshot_test_results = \
      self._test_properties_to_latest_test_result_matrix.get(matrix_index, [])

    self._set_test_case_failure_fault_attribution(failure_reason,
                                                  test_fault_attribute,
                                                  snapshot_test_results)
    self._test_properties_to_fault_attribute[(test_id, build_target, model)] \
      = test_fault_attribute
    if test_fault_attribute.snapshot_comparison_fault_attribution == \
        CqFailureAttribute.SUCCESS_FOUND:
      # This is classified as a new test failure. Determine and set
      # flakiness.
      self._set_test_case_failure_fault_attribution_flakiness(
          test_fault_attribute, failure_reason, build_target, model, test_id)

    self._dut_to_test_fault_attributes[(build_target,
                                        model)].append(test_fault_attribute)

  def _set_test_case_failure_fault_attribution_flakiness(
      self, test_fault_attribute: FaultAttributionProperties,
      failure_reason: str, build_target: str, model: str, test_id: str):
    """Sets the 'likely_flaky' property of the test_fault_attribute based
      on the number of failures present on a test case for the same failure
      reason.

      Args:
        test_fault_attribute: The fault attribute instance to set flakiness
          status for.
        failure_reason: The reason this test failed.
        build_target: The build target that this test case failure occurred
          on.
        model: The model that this test case failure occurred on. May be empty.
        test_id: The name of the test e.g. tast.critical-system
      """
    matrix_index = (build_target, model, test_id, failure_reason)
    likely_flaky = \
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

        return
      if all(snapshot_test_result.status == TestStatus.FAIL
             for snapshot_test_result in snapshot_test_results):
        if any(
            re.sub(IGNORED_FAILURE_REASON_TEXT, '', snapshot_test_result
                   .failure_reason.primary_error_message) == failure_reason
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

        return

    test_fault_attribute.snapshot_comparison_fault_attribution = CqFailureAttribute.NO_COMPARISON

  def _get_failed_test_names(self, hw_tests: SkylabResult,
                             vm_gce_tests: List[build_pb2.Build]):
    """Returns a list of all failed test names, and also sets failed HW and VM
    test properties on the class instance."""
    failed_test_names = set()
    for skylab_res in hw_tests:
      if not skylab_res.task.test.common.critical.value:
        continue
      for child_result in skylab_res.child_results:
        if child_result.state.verdict not in \
            VERDICTS_REQUIRING_FAULT_ATTRIBUTION + SUCCESS_VERDICTS:
          continue
        for test_case in child_result.test_cases:
          if test_case.verdict in SUCCESS_VERDICTS:
            test_id = test_case.name
            build_target = skylab_res.task.unit.common.build_target.name
            model = skylab_res.task.test.skylab_model or \
              EMPTY_MODEL
            self._passed_hw_tests.add((test_id, build_target, model))
            continue
          if test_case.verdict not in VERDICTS_REQUIRING_FAULT_ATTRIBUTION:
            continue
          # test_case.name here is analogous to the test_id substring in
          # the rdb test_result name.
          self._failed_hw_tests.append({
              'skylab_res': skylab_res,
              'child_result': child_result,
              'test_case': test_case
          })
          failed_test_names.add(test_case.name)

    # Store failed VM tests and get failed test names.
    for build in vm_gce_tests:
      if build.critical == Trinary.NO or build.status == Status.SUCCESS:
        continue
      if 'failed_test_cases' in build.output.properties:
        prop_struct = build.output.properties['failed_test_cases']
        test_failures = json_format.MessageToDict(prop_struct)
        for test_case in test_failures:
          self._failed_vm_tests.append({'build': build, 'test_case': test_case})
          test_id = self._get_vm_test_id(test_case)
          failed_test_names.add(test_id)

    return failed_test_names

  def _get_comparison_snapshots(self, orch_snapshot: GitilesCommit) \
      -> List[build_pb2.Build]:
    """Returns at most <SNAPSHOT_RETRIEVAL_LIMIT> snapshot builds
      ordered by start_time in descending order."""
    fields = frozenset(
        {'id', 'create_time', 'start_time', 'end_time', 'status'})

    if self.m.looks_for_green.stats.status \
        == LooksForGreenStatus.STATUS_RAN_OLDER:
      # LFG picked a different snapshot from the orchestrator. Use that.
      source_snapshot_build_commit_sha = \
        self.m.looks_for_green.stats.suggested.snap_commit_sha
    else:
      source_snapshot_build_commit_sha = orch_snapshot.id

    predicate_for_postsubmit_build_retrieval = builds_service_pb2.BuildPredicate(
        builder=POSTSUBMIT_PREDICATE_BUILDER_ID)
    retrieved_postsubmit_builds = self.m.buildbucket.search(
        [predicate_for_postsubmit_build_retrieval],
        limit=POSTSUBMIT_RETRIEVAL_LIMIT, fields=fields, timeout=60)

    tagValue = 'commit/gitiles/{}/{}/+/{}'.format(
        orch_snapshot.host, orch_snapshot.project,
        source_snapshot_build_commit_sha)
    predicate_for_snapshot_build_retrieval = builds_service_pb2.BuildPredicate(
        builder=SNAPSHOT_PREDICATE_BUILDER_ID)
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
        builder=SNAPSHOT_PREDICATE_BUILDER_ID,
        create_time=TimeRange(
            end_time=timestamp_pb2.Timestamp(
                # +1 to make this inclusive of the upper bound build
                seconds=upper_bound_build_for_search.create_time.ToSeconds() \
                        + 1
            )))
    previous_snapshot_builds = self.m.buildbucket.search(
        [predicate_for_previous_snapshot_builds],
        limit=SNAPSHOT_RETRIEVAL_LIMIT, fields=fields, timeout=60)
    started_builds = list(
        filter(self._has_build_started,
               previous_snapshot_builds + retrieved_postsubmit_builds))
    ordered_builds = sorted(started_builds,
                            key=(lambda build: build.start_time.seconds),
                            reverse=True)

    return ordered_builds

  def _retrieve_rdb_test_results(
      self, builds: List[build_pb2.Build],
      failed_test_names: Set[str]) -> Dict[str, Invocation]:
    """Retrieves test results from ResultDB for the given list of builds."""
    failed_test_names_regex = '|'.join(sorted(failed_test_names))
    fields = ['failureReason', 'status', 'variant']
    invocation_ids = list(
        map(lambda build: self._get_build_invocation_id(build.id), builds))

    return self.m.resultdb.query(inv_ids=invocation_ids, limit=0,
                                 tr_fields=fields,
                                 test_regex=failed_test_names_regex)

  def _set_comparison_matrices(
      self, invocation_id_to_invocation: Dict[str, Invocation],
      invocation_id_to_snapshot: Dict[str, build_pb2.Build]):
    """Sets the _test_properties_to_latest_test_result_matrix,
      _test_properties_to_latest_snapshot_matrix and
      _invocation_properties_to_failure_reason_count_matrix matrices to track
      the latest executions for each encountered test. Multiple
      attempts for the same test on the same build target are treated as unique
      entries, as they have unique invocation IDs. """
    # sort invocation_id_to_snapshot in order of descending snapshot build start
    # times
    invocation_id_and_snapshot_pairs = \
      sorted(invocation_id_to_snapshot.items(),
             key=(lambda element: element[1].start_time.seconds),
             reverse=True)
    for invocation_id, snapshot in invocation_id_and_snapshot_pairs:
      invocation = invocation_id_to_invocation[invocation_id]
      for test_result in invocation.test_results:
        if test_result.status == TestStatus.SKIP:
          continue

        test_id = self._get_test_id_from_rdb_test_name(test_result.name)
        if not test_id:
          # Test name wasn't in the expected format. Skipping.
          continue
        variant_dict = getattr(test_result.variant, 'def')
        build_target = variant_dict['build_target']
        # Incase a CQ test runs without any specific model, we should consider
        # a pseudo-model that represents the latest test results across all
        # models.

        models = [EMPTY_MODEL]
        if 'model' in variant_dict:
          models.append(variant_dict['model'])
        for model in models:
          matrix_index = (test_id, build_target, model)
          # If we haven't identified any snapshot to get results from for this
          # test, or if this is another attempt for the same test for an already
          # identified snapshot, append the test results.
          if matrix_index not in self._test_properties_to_latest_snapshot_matrix \
              or self._test_properties_to_latest_snapshot_matrix[
            matrix_index] == snapshot:
            self._test_properties_to_latest_test_result_matrix[
                matrix_index].append(test_result)
            self._test_properties_to_latest_snapshot_matrix[
                matrix_index] = snapshot

          if test_result.status != TestStatus.PASS:
            failure_reason = re.sub(
                IGNORED_FAILURE_REASON_TEXT, '',
                test_result.failure_reason.primary_error_message)
            self._invocation_properties_to_failure_reason_count_matrix[(
                build_target, model, test_id, failure_reason)] += 1

  def _get_build_invocation_id(self, build_id: int) -> str:
    return 'build-{}'.format(build_id)

  def _has_build_started(self, build: build_pb2.Build) -> bool:
    return build.status in (Status.SUCCESS, Status.FAILURE,
                            Status.INFRA_FAILURE, Status.STARTED)

  def _get_test_id_from_rdb_test_name(self, rdb_test_name: str) -> str:
    """Returns the test_id from a test_result name from rdb.

    rdb test names are of the format:
      "invocations/{INVOCATION_ID}/tests/{TEST_ID}/results/{RESULT_ID}".
    """
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
    comparison_snapshot_properties.source_started_unix_timestamp = \
      comparison_snapshot.start_time.seconds

    return comparison_snapshot_properties

  def _get_vm_test_id(self, test_case: Dict) -> str:
    """Returns the test_id for a vm / gce test prefixed with 'tast'.
    """

    # Some failed vm / gce test names within the build are not prefixed with
    # 'tast.' like how the invocation results are. For those cases, let's add
    # the prefix.
    test_prefix = 'tast.'
    test_id = test_case['name'] if test_case['name'].startswith(test_prefix) \
      else test_prefix + test_case['name']

    return test_id
