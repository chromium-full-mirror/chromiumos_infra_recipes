# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Dict, List, Tuple

from google.protobuf import json_format, timestamp_pb2

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.recipe_modules.chromeos.exonerate.exonerate import FailedTestStats
from PB.recipe_modules.chromeos.exonerate.exonerate import OverallTestStats
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon

from RECIPE_MODULES.chromeos.gerrit.api import Label
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest

from recipe_engine import recipe_api


# Start looking back at 1 days worth of data while we are still developing.
DEFAULT_LOOKBACK_SECONDS = 60 * 60 * 24 * 1

# Limits on the number of builds and suites that will be listed out in comments.
# Doesn't affect retry behavior.
DEFAULT_BUILDS_COMMENT_LIMIT = 5
DEFAULT_SUITES_COMMENT_LIMIT = 5

RETRYABLE_STATUSES = [
    bb_common_pb2.FAILURE,
    bb_common_pb2.INFRA_FAILURE,
]


class AutoRetryUtilApi(recipe_api.RecipeApi):
  """A module for util functions associated with the CQ auto retries."""

  @property
  def lookback_seconds(self):
    return self._lookback_seconds

  @property
  def builds_comment_limit(self):
    return self._builds_comment_limit

  @property
  def suites_comment_limit(self):
    return self._suites_comment_limit

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._lookback_seconds = props.lookback_seconds or DEFAULT_LOOKBACK_SECONDS
    self._builds_comment_limit = props.builds_comment_limit or DEFAULT_BUILDS_COMMENT_LIMIT
    self._suites_comment_limit = props.suites_comment_limit or DEFAULT_SUITES_COMMENT_LIMIT

  def initialize(self):
    self._cq_orch_default_child_buiders = [
        c.name for c in self.m.cros_infra_config.get_builder_config(
            'cq-orchestrator').orchestrator.child_specs
    ]

  def _get_child_builders(
      self, cq_run: build_pb2.Build) -> Tuple[List[str], List[str]]:
    """Returns the names of the child builders for the given cq-orchestrator.

    Args:
      cq_run: The cq-orchestrator build for which to get the child builders.

    Returns:
      successful_builders, unsuccessful_builders: A tuple of the names of the
          child builders categorized by whether they passed or not.
    """
    successful_builders = []
    unsuccessful_builders = []
    output_dict = json_format.MessageToDict(cq_run.output.properties)
    child_build_info = output_dict.get('child_build_info', [])

    for b in child_build_info:
      relevant = b.get('relevant', False)
      builder_name = b.get('builder', {}).get('builder')
      status = b.get('status')

      if not relevant:
        continue
      if status == 'SUCCESS':
        successful_builders.append(builder_name)
      else:
        unsuccessful_builders.append(builder_name)

    return successful_builders, unsuccessful_builders

  def analyze_build_failures(
      self, cq_run: build_pb2.Build) -> Tuple[List[str], List[str], List[str]]:
    with self.m.step.nest('analyzing build results') as pres:
      retryable_failure_builders = []
      outstanding_failure_builders = []

      successful_builders, unsuccessful_builders = self._get_child_builders(
          cq_run)

      # Builders which failed but are not longer CQ blockers are now retryable.
      active_cq_verifiers = self._submission_blocking_builders(cq_run)
      removed_verifier_failure_builders = [
          b for b in unsuccessful_builders if b not in active_cq_verifiers
      ]
      retryable_failure_builders.extend(removed_verifier_failure_builders)
      outstanding_failure_builders = [
          b for b in unsuccessful_builders
          if b not in retryable_failure_builders
      ]

      pres.step_text = '%d success, %d retryable, %d outstanding' % (
          len(successful_builders), len(retryable_failure_builders),
          len(outstanding_failure_builders))
      pres.logs['successful_builders'] = sorted(successful_builders)
      pres.logs['retryable_failure_builders'] = sorted(
          retryable_failure_builders)
      pres.logs['outstanding_failure_builders'] = sorted(
          outstanding_failure_builders)

    return (successful_builders, retryable_failure_builders,
            outstanding_failure_builders)

  def analyze_test_results(
      self, cq_run: build_pb2.Build) -> Tuple[List[str], List[str], List[str]]:
    """Returns a list of test suite names grouped by retryable status.

    Args:
      cq_run: The cq-orchestrator for which to analyze the test results.

    Returns:
      A tuple containing 3 lists of test suite names grouped by whether the
          suite was successful, failed but is retryable, or failed and is not
          retriable.
    """
    with self.m.step.nest('analyzing test results') as pres:

      output_dict = json_format.MessageToDict(cq_run.output.properties)
      test_summary = output_dict.get('test_summary', [])

      successful_test_suite_names = []
      retryable_test_suite_names = []
      outstanding_failure_test_suite_names = []

      # Failures on builders that are no longer blocking CQ submission are now
      # retryable.
      active_cq_verifiers = self._submission_blocking_builders(cq_run)
      for t in test_summary:
        name = t.get('name')
        status = t.get('status')
        critical = t.get('critical')
        # TODO(b/291769254): Remove fallback to parsing the name a few days
        # after https://crrev.com/c/4718546 is deployed to prod.
        builder_name = t.get('builder_name', t.get('name', '').split('.')[0])

        if status == 'SUCCESS' or not critical:
          successful_test_suite_names.append(name)
        elif builder_name not in active_cq_verifiers:
          retryable_test_suite_names.append(name)
        else:
          outstanding_failure_test_suite_names.append(name)

      pres.step_text = '%d success, %d retryable, %d outstanding' % (
          len(successful_test_suite_names), len(retryable_test_suite_names),
          len(outstanding_failure_test_suite_names))
      pres.logs['successful_test_suite_names'] = sorted(
          successful_test_suite_names)
      pres.logs['retryable_test_suite_names'] = sorted(
          retryable_test_suite_names)
      pres.logs['outstanding_failure_test_suite_names'] = sorted(
          outstanding_failure_test_suite_names)
      return (successful_test_suite_names, retryable_test_suite_names,
              outstanding_failure_test_suite_names)

  def _submission_blocking_builders(self, cq_run: build_pb2.Build) -> List[str]:
    """Returns the names of builders which block submission for this CQ run.

    A blocking builder is a builder which must pass in order for the CQ run to
    succeed.

    Currently, blocking builders are defined as all the builders in the
    cq-orchestrator's child specs in addition to all builders which were
    explicitly forced relevant via CL footers.

    This does not currently take into account RUN_WHEN rules.

    Args:
      cq_run: The CQ run for which to get blocking builders.
    """
    forced_relevant_builders = []
    if 'found_force_relevant_targets' in cq_run.output.properties:
      forced_relevant_builders = list(
          cq_run.output.properties['found_force_relevant_targets'])
    return self._cq_orch_default_child_buiders + forced_relevant_builders

  def _get_current_cq_orchs_with_retryable_statuses(
      self) -> List[build_pb2.Build]:
    """Returns cq-orchestrators that are "current" and have a retryable status.

    "Current" means that the cq-orchestrator was the most recent cq-orchestrator
    run for that cq_cl_group.
    """

    with self.m.step.nest('query for cq-orchestrators') as pres:
      builder = builder_common_pb2.BuilderID(builder='cq-orchestrator',
                                             bucket='cq', project='chromeos')
      create_time = bb_common_pb2.TimeRange(
          start_time=timestamp_pb2.Timestamp(
              seconds=int(self.m.buildbucket.build.start_time.seconds) -
              self.lookback_seconds))
      search_predicate = builds_service_pb2.BuildPredicate(
          builder=builder, create_time=create_time)

      # The builds are returned ordered from newest-to-oldest.
      fields = self.m.buildbucket.DEFAULT_FIELDS | {'tags'}
      cq_orch_runs = self.m.buildbucket.search(search_predicate, fields=fields)
      cq_orch_runs = sorted(cq_orch_runs,
                            key=lambda build: build.create_time.seconds,
                            reverse=True)

      # Get the latest cq-orchestrator run for each cq_cl_group.
      cl_group_to_run_mapping = {}
      for x in cq_orch_runs:
        cq_cl_group = self.m.cros_tags.get_single_value('cq_cl_group_key',
                                                        x.tags)
        if cq_cl_group not in cl_group_to_run_mapping:
          cl_group_to_run_mapping[cq_cl_group] = x

      # Only return the builds with a retryable status.
      builds = [
          x for x in cl_group_to_run_mapping.values()
          if x.status in RETRYABLE_STATUSES
      ]
      pres.step_text = 'found %d builds' % len(builds)
      for b in builds:
        pres.links[b.id] = self.m.buildbucket.build_url(build_id=b.id)
      return builds

  def _has_supported_failure_mode(self, cq_orch: build_pb2.Build) -> bool:
    """Returns whether a cq-orchestrator had a supported failure mode.

    Currently only child build failures and end-to-end test failures are
    supported. Other failures in the cq-orchestrator execution
    (e.g. merge conflict) are not currently retryable.

    Args:
      cq_orch: The cq-orchestrator run to consider.

    Returns:
      Whether the cq-orchestrator had a failure which may be auto-retryable.
    """
    return ('has_child_failures' in cq_orch.output.properties and
            cq_orch.output.properties['has_child_failures'])

  def cq_retry_candidates(self) -> List[build_pb2.Build]:
    """Returns cq-orchestrator builds which may be elegible for auto retry.

    # TODO(b/291767456): Expand to include all criteria listed in the bug.
    Candidate cq-orchestrator builds must meet the following criteria:
      * The build status is in RETRYABLE_STATUSES.
      * The build is the latest cq attempt for the CLs under test.
      * The build had a supported failure mode.
    """
    cq_orchs = self._get_current_cq_orchs_with_retryable_statuses()
    cq_orchs = [c for c in cq_orchs if self._has_supported_failure_mode(c)]

    return cq_orchs

  def test_variant_exoneration_analysis(
      self, cq_run: build_pb2.Build
  ) -> Tuple[List[FailedTestStats], List[FailedTestStats],
             List[FailedTestStats]]:
    """Runs auto exoneration analysis and returns categorized FailedTestStats.

    Uses the FailedTestStats reported in the output properties of the
    cq-orchestrator to query LUCI analysis for updated exoneration status of the
    failed test cases in a build.

    Note: A test which was previously exonerated will not be updated such that
    it is no longer exonerated for the CQ run.

    Args:
      cq_run: The cq-orchestrator for which to retrieve updated FailedTestStats.

    Returns:
      A tuple containing 3 lists of FailedTestStats grouped by whether the test
          variant is previously exonerated, newly exonerated, or not exonerated.
    """

    def _categorize_stats(stats):
      exonerated = []
      not_exonerated = []
      for t in stats:
        if t.manually_exonerated or t.automatically_exonerated:
          exonerated.append(t)
        else:
          not_exonerated.append(t)
      return exonerated, not_exonerated

    with self.m.step.nest('exoneration analysis') as pres:
      output_dict = json_format.MessageToDict(cq_run.output.properties)
      stats = output_dict.get('failed_test_stats', {})
      overall_stats = json_format.ParseDict(stats, OverallTestStats())

      newly_exonerated_stats = []
      previously_exonerated_stats, outstanding_failure_stats = _categorize_stats(
          overall_stats.failed_tests)

      # Exit early if there are no outstanding test variant failures or
      # exoneration was overridden.
      if len(overall_stats.failed_tests) == 0:
        pres.step_text = 'skipping: no test variant failures'
        return (previously_exonerated_stats, newly_exonerated_stats,
                outstanding_failure_stats)
      if overall_stats.override_info.override_reason:
        pres.step_text = 'skipping: overridden by guardrails'
        return (previously_exonerated_stats, newly_exonerated_stats,
                outstanding_failure_stats)
      if all(t.manually_exonerated or t.automatically_exonerated
             for t in overall_stats.failed_tests):
        pres.step_text = 'skipping: no outstanding failures'
        return (previously_exonerated_stats, newly_exonerated_stats,
                outstanding_failure_stats)

      # Only update the failed test stats for test variants which were not already
      # exonerated.
      # This is done to prevent a test variant which was previously exonerated
      # reporting back that it is no longer exonerable based on recent runs. This
      # might no longer be a concern once exoneration takes into account commit
      # position.
      variants = [
          self.m.exonerate.get_test_variant_dict(test_id=t.test_id,
                                                 board=t.board,
                                                 build_target=t.build_target,
                                                 model=t.model)
          for t in outstanding_failure_stats
      ]
      failure_rates = self.m.exoneration_util.query_failure_rate(variants)
      # TODO(b/291768475): Check that new exonerations do not exceed guardrails.
      updated_stats = self.m.exonerate.generate_failed_test_stats(failure_rates)

      newly_exonerated_stats, outstanding_failure_stats = _categorize_stats(
          updated_stats)

      pres.step_text = '%d previously exonerated, %d newly exonerated, %d outstanding' % (
          len(previously_exonerated_stats), len(newly_exonerated_stats),
          len(outstanding_failure_stats))

      return (previously_exonerated_stats, newly_exonerated_stats,
              outstanding_failure_stats)

  # TODO(b/291768475): Calculate override info before exonerating and filter out
  # previously exonerated suites.
  def get_exonerated_suites(
      self, cq_run: build_pb2.Build,
      failed_test_stats: List[FailedTestStats]) -> List[str]:
    """Returns the names of the exonerated test suites for the given CQ run.

    Args:
      cq_run: The cq-orchestrator build for which to get the exonerated suites.
      failed_test_stats: A list of FailedTestStats to use when performing
          auto exoneration rathen that the FailedTestStats in the output
          properties of the build. This list of FailedTestStats should be
          updated using the latest LUCI analysis data.

    Returns:
      The names of the exonerated test suites.
  """

    def _hw_unit(test_summary_dict: Dict) -> UnitHwTest:
      """Returns a UnitHwTest created using info from the test summary dict.

      Args:
        test_summary_dict: Information about a test suite result. This includes
            display name, build_target, criticality, and status.
            If applicable, also includes board and model.

      Returns:
        A UnitHwTest based on info found in the test summary dict.
      """
      target_name = test_summary_dict['build_target']
      display_name = test_summary_dict['name']
      critical = test_summary_dict['critical']
      builder_name = test_summary_dict['builder_name']
      suite = display_name.split('.')[-1]
      hw_test = HwTestCfg.HwTest(
          common=TestSuiteCommon(display_name=display_name,
                                 critical={'value': critical}),
          suite=suite,
          # TODO(b/289095330): Populate model in test_summary and pass
          # it in here when a specific model is requested.
          skylab_model='',
      )
      unit = HwTestUnit(
          common=TestUnitCommon(
              build_target=BuildTarget(name=target_name),
              builder_name=builder_name,
          ),
          hw_test_cfg=HwTestCfg(
              hw_test=[hw_test],
          ),
      )
      return UnitHwTest(unit=unit, hw_test=hw_test)

    # Get the test result from the test builders.
    output_dict = json_format.MessageToDict(cq_run.output.properties)
    test_summary = output_dict.get('test_summary', [])
    test_tasks = output_dict.get('test_tasks', {})
    skylab_builder_ids = [
        int(b) for b in test_tasks.get('skylab_builder_ids', [])
    ]
    tast_vm_tests_builder_ids = [
        int(b) for b in test_tasks.get('tast_vm_tests_builder_ids', [])
    ]

    # Generate the exoneration configs for this specific CQ run.
    exon_configs = self.m.exoneration_util.get_updated_configs(
        failed_test_stats, self.m.exonerate.manual_exoneration_configs)

    exonerated_suites = []
    # Exonerate HW test results.
    if len(skylab_builder_ids) > 0:
      hw_units = [
          _hw_unit(t) for t in test_summary if '.hw.' in t.get('name', '')
      ]
      hw_test_results = self.m.skylab_results.get_previous_results(
          skylab_builder_ids, hw_units)
      exonerated_suites.extend([
          self.m.naming.get_skylab_result_title(result)
          for result in hw_test_results
          if self.m.exonerate.is_hw_result_exonerable(result, exon_configs)
      ])
    # Exonerate VM test results.
    if len(tast_vm_tests_builder_ids) > 0:
      vm_builds = self.m.buildbucket.get_multi(
          tast_vm_tests_builder_ids).values()
      exonerated_suites.extend([
          self.m.naming.get_vm_test_title(result)
          for result in vm_builds
          if self.m.exonerate.is_vm_test_build_exonerable(result, exon_configs)
      ])

    return exonerated_suites

  def _create_comment(self, build: build_pb2.Build,
                      retryable_builders: List[str],
                      retryable_test_suites: List[str]) -> str:
    """Create a comment explaining why the build was retried.

    Does formatting of the comment, e.g. truncating the lists of builds / test
    suites if they are very long.

    Args:
      build: The build to retry.
      retryable_builders: Names of the child builders that are now retryable.
      retryable_test_suites: Names of the test suites that are now retryable.

    Returns:
      A string comment.
    """
    comment = f'The previous build (ci.chromium.org/b/{build.id}) is being automatically retried for the following reasons:\n'
    if retryable_builders:
      comment += '- Some child builders are now retriable:'
      if len(retryable_builders) <= self.builds_comment_limit:
        comment += ', '.join(retryable_builders) + '\n'
      else:
        comment += ', '.join(
            retryable_builders[:self.builds_comment_limit]) + ',...\n'

    if retryable_test_suites:
      comment += '- Some tests are now retriable:'
      if len(retryable_test_suites) <= self.suites_comment_limit:
        comment += ', '.join(retryable_test_suites) + '\n'
      else:
        comment += ', '.join(
            retryable_test_suites[:self.suites_comment_limit]) + ',...\n'

    return comment

  def retry_build(
      self,
      build: build_pb2.Build,
      retryable_builders: List[str],
      retryable_test_suites: List[str],
  ):
    """Retries build by voting on all of its input changes.

    Sets Commit-Queue+1 or 2 (depending on whether build was a dry run)
    on all of build's input changes. It is assumed that all other labels
    required for submission are set. Also leaves a comment explaining why the
    build was retried.

    At least one of retryable_builders and retryable_test_suites must be
    non-empty.

    Args:
      build: The build to retry.
      retryable_builders: Names of the child builders that are now retryable.
      retryable_test_suites: Names of the test suites that are now retryable.
    """
    if not retryable_builders and not retryable_test_suites:
      raise ValueError(
          'At least one builder or test suite must be given as a retry reason')

    comment = self._create_comment(build, retryable_builders,
                                   retryable_test_suites)

    with self.m.step.nest(f'retry build {build.id}'):
      dry_run = build.input.properties['$recipe_engine/cq'][
          'runMode'] == self.m.cq.DRY_RUN
      labels = {
          Label.COMMIT_QUEUE: 1 if dry_run else 2,
      }
      for gc in build.input.gerrit_changes:
        self.m.gerrit.set_change_labels_remote(gc, labels)
        self.m.gerrit.add_change_comment_remote(gc, comment)
