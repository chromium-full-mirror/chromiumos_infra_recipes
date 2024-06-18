# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility function for CQ auto retry."""

import collections
import dataclasses
import functools
from typing import Dict, FrozenSet, Iterable, List, NamedTuple, Set, Optional, Tuple

from google.protobuf import json_format, timestamp_pb2

from PB.chromiumos import builder_config as builder_config_pb2
from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import RetryDetails
from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution import CqTestFailureFaultAttributionStats, CqFailureAttribute
from PB.recipe_modules.chromeos.exonerate.exonerate import FailedTestStats
from PB.recipe_modules.chromeos.exonerate.exonerate import OverallTestStats
from PB.recipe_modules.chromeos.failures.failures import PackageFailure
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStatus
from PB.testplans.target_test_requirements_config import HwTestCfg
from PB.testplans.target_test_requirements_config import TestSuiteCommon
from PB.testplans.generate_test_plan import HwTestUnit
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.test_platform.taskstate import TaskState

from RECIPE_MODULES.chromeos.cros_history.api import PASSED_TESTS_KEY
from RECIPE_MODULES.chromeos.gerrit.api import Label
from RECIPE_MODULES.chromeos.gerrit.api import PatchSet
from RECIPE_MODULES.chromeos.looks_for_green.api import Snapshot
from RECIPE_MODULES.chromeos.skylab_results.api import PrejobStats
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult, UnitHwTest

from recipe_engine import recipe_api

# The Chromeos LUCI service account.
CHROMEOS_LUCI_SERVICE_ACCOUNT = 'chromeos-scoped@luci-project-accounts.iam.gserviceaccount.com'

# ChromeOS LUCI auth account identity.
CHROMEOS_LUCI_AUTH_IDENTITY = 'project:chromeos'

CQ_MINIMAL_SUITE_NAME = 'cq-minimal'

# Start looking back at 1 days worth of data while we are still developing.
DEFAULT_LOOKBACK_SECONDS = 60 * 60 * 24 * 1

# Limits on the number of builds and suites that will be listed out in comments.
# Doesn't affect retry behavior.
DEFAULT_BUILDS_COMMENT_LIMIT = 5
DEFAULT_SUITES_COMMENT_LIMIT = 5

# The service account considered as one of the auto retries.
DEFAULT_RETRY_SERVICE_ACCOUNT = 'chromeos-auto-retry@chromeos-bot.iam.gserviceaccount.com'

# The default setting for the global throttle.
DEFAULT_24_HR_THROTTLE = 300
DEFAULT_2_HR_THROTTLE = 30

# Experiment with retrying any infra failures.
# TODO(b/296441878): Remove post-launch.
EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES = 'retry-infra-failures'
# Experiment with retrying any prejob failures.
# TODO(b/296441878): Remove post-launch.
EXPERIMENTAL_FEATURE_RETRY_PREJOB_FAILURES = 'retry-prejob-failures'
EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN = 'wait-for-green'
EXPERIMENTAL_FEATURE_RETRY_SDK_FAILURES = 'retry-sdk-failures'
EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES = 'retry-attributed-failures'

EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES = 'retry-not-at-fault-package-failures'

RETRYABLE_STATUSES = [
    bb_common_pb2.FAILURE,
    bb_common_pb2.INFRA_FAILURE,
]

RETRY_OPTIONS_FOOTER_KEY = 'RetryOptions'
RETRY_OPTIONS_EXEMPT_VALUE = 'None'

# Child builders that don't init an SDK. This is needed for the SDK failure
# retry analysis; we want to know if any of the child builders were able to
# init an SDK, but these builders should not count as successful.
#
# If there are more of these type of builder in the future, this check should
# be made based on an input property or similar.
NO_SDK_CHILD_BUILDERS = {'bazel-test-cq'}


class BasicClInfo(NamedTuple):
  """Basic information about the change list."""
  host: str
  change: str


@dataclasses.dataclass
class WaitForGreenStats:
  """Per-build statistics about wait-for-green retries."""
  # Total number of builders found in the snapshot the build ran on. This may be
  # 0 during normal operation, if the builder ran on a recent snapshot for
  # which greenness is not yet published.
  total_builders_in_snapshot: int = 0

  # The names of the failed builders in the snapshot the build ran on. The
  # CQ build being considered for retry did not necessarily fail on these
  # builders (e.g. the builder may not have been relevant to the CQ build, or
  # could be a flaky failure that failed on the snapshot build but passed on the
  # CQ build).
  failed_builders_in_snapshot: List[str] = dataclasses.field(
      default_factory=list)

  # The names of the builders that were not green in the snapshot the build ran
  # on that are green on the snapshot found by looks for green.
  now_green_builders: List[str] = dataclasses.field(default_factory=list)

  # The names of the builders that are now retryable. This is the intersection
  # of the builders that failed for the build and now_green_builders. Note that
  # PerBuildStats also has a list of retryable builders, this list is the subset
  # of builders that are retryable because they are now green.
  retryable_builders: List[str] = dataclasses.field(default_factory=list)

  # The names of builders that failed for the CQ build, but do not have
  # greenness data published. This is possible because not all CQ builders have
  # a snapshot equivalent (e.g. postsubmit testing for the buildtest builders
  # runs in an informational workflow).
  # If there are builders that are now retryable (as defined by the
  # retryable_builders field), assume that the ones without greenness reported
  # are also retryable.
  #
  # TODO(b/299561567): See if we can address this.
  no_snapshot_data_retryable_builders: List[str] = dataclasses.field(
      default_factory=list)


@dataclasses.dataclass
class PerBuildStats:
  """Statistics specific to a candidate build, for monitoring and debugging.

  AutoRetryUtilApi has a map from build id -> PerBuildStats which should be
  updated by various functions as auto-retry decisions are made. This map should
  be published as an output property after all auto-retry decisions are made, by
  publish_per_build_stats.
  """
  # The names of the failed builders that are now retryable.
  retryable_builders: List[str] = dataclasses.field(default_factory=list)

  # The names of the failed builders that are not retryable.
  outstanding_builders: List[str] = dataclasses.field(default_factory=list)

  # The names of the failed test suites that are now retryable.
  retryable_test_suites: List[str] = dataclasses.field(default_factory=list)

  # The names of the failed test suites that are not retryable.
  outstanding_test_suites: List[str] = dataclasses.field(default_factory=list)

  wait_for_green_stats: WaitForGreenStats = dataclasses.field(
      default_factory=WaitForGreenStats)

  # The reasons why this CQ run was not retried.
  filter_reasons: List[str] = dataclasses.field(default_factory=list)


def _lfg_skipped(cq_orch: build_pb2.Build) -> bool:
  """Returns if cq_orch skipped looking for green.

  Checks the looks_for_green.status output property and returns true if it is
  any of the STATUS_SKIPPED values. Note that if this output property is missing
  this function also returns true.
  """
  lfg_prop = cq_orch.output.properties.get_or_create_struct('looks_for_green')
  if 'status' not in lfg_prop:
    return True
  status = lfg_prop['status']
  return LooksForGreenStatus.Value(status) in (
      LooksForGreenStatus.STATUS_SKIPPED_CQ_DEPEND,
      LooksForGreenStatus.STATUS_SKIPPED_STACKED_CHANGES,
      LooksForGreenStatus.STATUS_SKIPPED_DISALLOW,
      LooksForGreenStatus.STATUS_SKIPPED_MERGE_COMMIT,
  )


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

  def __init__(self, props: AutoRetryUtilProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._lookback_seconds = props.lookback_seconds or DEFAULT_LOOKBACK_SECONDS
    self._builds_comment_limit = props.builds_comment_limit or DEFAULT_BUILDS_COMMENT_LIMIT
    self._suites_comment_limit = props.suites_comment_limit or DEFAULT_SUITES_COMMENT_LIMIT
    self._enable_retries = props.enable_retries
    self._retry_service_account = props.service_account or DEFAULT_RETRY_SERVICE_ACCOUNT
    self._throttle_24hr = props.throttle_24hr or DEFAULT_24_HR_THROTTLE
    self._throttle_2hr = props.throttle_2hr or DEFAULT_2_HR_THROTTLE
    self._experimental_features = {
        x.name: x.experiment_flag for x in props.experimental_features
    }
    self._chromeos_luci_service_account = (
        props.chromeos_luci_service_account or CHROMEOS_LUCI_SERVICE_ACCOUNT)

    # Cache snapshot greenness based on commit. Note that it is possible the
    # greenness for a snapshot isn't published when it is first looked up
    # (buildbucket_stats.get_snapshot_greenness returns None), in that case
    # later calls to get greenness for that snapshot will also return None.
    self._snapshot_greenness_cache: Dict[
        str, Optional[collections.OrderedDict]] = {}

    self._filtered_build_stats = {}
    self.per_build_stats: Dict[int, PerBuildStats] = collections.defaultdict(
        PerBuildStats)
    self._experimental_retries: Dict[int, Set] = collections.defaultdict(set)
    self._multi_retry_config: AutoRetryUtilProperties.MultiRetryConfig = props.multi_retry_config
    if not self._multi_retry_config.max_retries:
      self._multi_retry_config.max_retries = 1

    # We must have a backoff strategy if more than one auto-retry is used.
    # Nocover because tests can't expect_exception for exceptions thrown raised
    # from __init__.
    if self._multi_retry_config.max_retries > 1 and not self._multi_retry_config.WhichOneof(
        'backoff_strategy'):  # pragma: nocover
      raise ValueError('backoff_strategy must be set if max_retries > 1')

  def initialize(self):
    # enable_retries should never be set on a staging builder.
    # api.expect_exception doesn't work on exceptions thrown from initialize, so
    # don't cover this case.
    self.m.cros_infra_config.determine_if_staging()
    if self.m.cros_infra_config.is_staging and self._enable_retries:  # pragma: nocover
      raise ValueError('enable_retries should not be set on staging builders')

    self._cq_orch_default_child_buiders = [
        c.name for c in self.m.cros_infra_config.get_builder_config(
            'cq-orchestrator').orchestrator.child_specs
    ]

    # Set as the initial value for lookback_hours since the value of
    # lookback_hours can be mutated in subsequent calls to
    # resize_lfg_lookback().
    self._lfg_lookback_hours = self.m.looks_for_green.lookback_hours

  @property
  def experimental_retries(self):
    return self._experimental_retries

  def is_experimental_feature_enabled(self, feature_name: str,
                                      build: build_pb2.Build):
    """Returns whether the given feature is enabled on the build."""
    if feature_name not in self._experimental_features:
      return False

    experiment_flag = self._experimental_features[feature_name]
    return not experiment_flag or experiment_flag in build.input.experiments

  def _get_recent_retry_sum(self, lookback_hours: int) -> int:
    """Return the sum of retries made by the same builder in the window.

    Args:
      lookback_hours: The number of hours to look back for our builds.
    Returns:
      prev_retry_sum: The number of retries made in the previous runs.
    """
    builder = self.m.buildbucket.build.builder
    create_time = bb_common_pb2.TimeRange(
        start_time=timestamp_pb2.Timestamp(
            seconds=int(self.m.buildbucket.build.start_time.seconds) -
            lookback_hours * 60 * 60))
    search_predicate = builds_service_pb2.BuildPredicate(
        builder=builder, create_time=create_time)

    prev_runs = self.m.buildbucket.search(search_predicate)

    prev_retry_sum = 0
    for r in prev_runs:
      r_props = json_format.MessageToDict(r.output.properties)
      prev_retry_sum += r_props.get('retries_made', 0)
    return prev_retry_sum

  def unthrottled_retries_left(self) -> int:
    """Returns the number of retries left below the 24 and 2 hour throttles."""
    short_term_tries = max(self._throttle_2hr - self._get_recent_retry_sum(2),
                           0)
    long_term_tries = max(self._throttle_24hr - self._get_recent_retry_sum(24),
                          0)
    return min(short_term_tries, long_term_tries)

  def _get_child_builders(
      self, cq_run: build_pb2.Build) -> Tuple[List[str], List[str], List[str]]:
    """Returns the names of the child builders for the given cq-orchestrator.

    Args:
      cq_run: The cq-orchestrator build for which to get the child builders.

    Returns:
      successful_builders, unsuccessful_builders, retryable_builders: A tuple of
          the names of the child builders categorized by whether they passed,
          are outstanding failures, or are retryable failures.
    """
    successful_builders = []
    unsuccessful_builders = []
    infra_failure_builders = []
    retryable_builders = []
    output_dict = json_format.MessageToDict(cq_run.output.properties)
    child_build_info = output_dict.get('child_build_info', [])

    for b in child_build_info:
      builder_name = b.get('builder', {}).get('builder')
      status = b.get('status')
      collect_value = b.get('collect_value')

      # If a builder does not have a collect handling value it is likely not an
      # image builder. If it is set to "NO_COLLECT" then the build is
      # non-critical.
      if collect_value not in [
          builder_config_pb2.BuilderConfig.Orchestrator.ChildSpec
          .CollectHandling.Name(builder_config_pb2.BuilderConfig.Orchestrator
                                .ChildSpec.COLLECT_AFTER_HW_TEST),
          builder_config_pb2.BuilderConfig.Orchestrator.ChildSpec
          .CollectHandling.Name(
              builder_config_pb2.BuilderConfig.Orchestrator.ChildSpec.COLLECT),
      ]:
        continue

      if status == bb_common_pb2.Status.Name(bb_common_pb2.SUCCESS):
        successful_builders.append(builder_name)
      # TODO(b/299482781): Remove post-launch.
      elif self.is_experimental_feature_enabled(
          EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES,
          cq_run) and status == bb_common_pb2.Status.Name(
              bb_common_pb2.INFRA_FAILURE):
        infra_failure_builders.append(builder_name)
      else:
        unsuccessful_builders.append(builder_name)

    # Child build infra failures are only retryable if other child builds did
    # not infra failure as it gives indication of a possible flake.
    if infra_failure_builders and (successful_builders or
                                   unsuccessful_builders):
      retryable_builders.extend(infra_failure_builders)
      self._experimental_retries[cq_run.id].add(
          EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES)
    else:
      unsuccessful_builders.extend(infra_failure_builders)

    return successful_builders, unsuccessful_builders, retryable_builders

  def analyze_build_failures(
      self, cq_run: build_pb2.Build) -> Tuple[List[str], List[str], List[str]]:
    with self.m.step.nest('analyzing build results') as pres:
      outstanding_failure_builders = []

      successful_builders, unsuccessful_builders, retryable_failure_builders = self._get_child_builders(
          cq_run)

      # Builders which failed but are not longer CQ blockers are now retryable.
      active_cq_verifiers = self._submission_blocking_builders(cq_run)
      removed_verifier_failure_builders = [
          b for b in unsuccessful_builders
          if b.replace('-slim-cq', '-cq') not in active_cq_verifiers
      ]
      retryable_failure_builders.extend(removed_verifier_failure_builders)
      outstanding_failure_builders = [
          b for b in unsuccessful_builders
          if b not in retryable_failure_builders
      ]

      retryable_failure_builders.extend(
          self._waits_for_green_retryable_builders(
              cq_run, outstanding_failure_builders))
      outstanding_failure_builders = [
          b for b in unsuccessful_builders
          if b not in retryable_failure_builders
      ]

      retryable_failure_builders.extend(
          self._unrelated_package_failures_retryable_builders(
              cq_run, outstanding_failure_builders))
      outstanding_failure_builders = [
          b for b in unsuccessful_builders
          if b not in retryable_failure_builders
      ]

      # If there were any successful child builders, it means the SDK failures
      # are likely not the fault of the CL. Even pointless successful builds
      # needed to init and update the SDK. Add all the SDK failures as
      # retryable.
      # TODO(b/337243561): Determine if this retry mode is still necessary.
      if outstanding_failure_builders and self.is_experimental_feature_enabled(
          EXPERIMENTAL_FEATURE_RETRY_SDK_FAILURES, cq_run
      ) and successful_builders and not NO_SDK_CHILD_BUILDERS.issuperset(
          successful_builders):
        retryable_sdk_failures = self._get_sdk_failures(cq_run)
        if retryable_sdk_failures:
          self._experimental_retries[cq_run.id].add(
              EXPERIMENTAL_FEATURE_RETRY_SDK_FAILURES)
        retryable_failure_builders.extend(
            [b for b in unsuccessful_builders if b in retryable_sdk_failures])

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

      self.per_build_stats[cq_run.id].retryable_builders = sorted(
          retryable_failure_builders)
      self.per_build_stats[cq_run.id].outstanding_builders = sorted(
          outstanding_failure_builders)

    return (successful_builders, retryable_failure_builders,
            outstanding_failure_builders)

  def _unrelated_package_failures_retryable_builders(
      self, cq_run: build_pb2.Build,
      outstanding_failure_builders: List[str]) -> List[str]:
    """Returns a list of builders with retryable unrelated package failures."""
    retryable_builders = []

    if not self.is_experimental_feature_enabled(
        EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES, cq_run):
      return retryable_builders

    not_at_fault_builders = self._get_not_cl_affected_package_failure_builders(
        cq_run, outstanding_failure_builders)

    # Return early if there are no candidates.
    if not not_at_fault_builders:
      return retryable_builders

    failed_on_snapshot_builders = self._failed_on_snapshot_builders(cq_run)

    builder_greenness_dict = self._get_snapshot_builder_greenness_dict(
        cq_run.output.gitiles_commit.id)
    if failed_on_snapshot_builders is not None:
      not_at_fault_retryable_builders = [
          b for b in not_at_fault_builders
          # Builders which failed on snapshot should not be retried until
          # "wait-for-green" kicks in.
          if self.m.naming.get_snapshot_builder_name(b) in
          builder_greenness_dict and self.m.naming.get_snapshot_builder_name(
              b) not in failed_on_snapshot_builders
      ]
      if not_at_fault_retryable_builders:
        self._experimental_retries[cq_run.id].add(
            EXPERIMENTAL_FEATURE_RETRY_NOT_AT_FAULT_PACKAGE_FAILURES)
        retryable_builders = not_at_fault_retryable_builders
    return retryable_builders

  def _cq_retry_snapshot(self, cq_run: build_pb2.Build,
                         builders: List[str]) -> Optional[Snapshot]:
    """Return the Snapshot that the CQ retry would use."""
    with self.m.step.nest('determine CQ retry snapshot') as pres:
      if _lfg_skipped(cq_run):
        current_greenness = self._latest_greenness
        step_text_prefix = 'build skipped LFG, using latest scored snapshot'
      else:
        lfg_lookback_hours = self.m.looks_for_green.resize_lfg_lookback(
            cq_run.input.gerrit_changes, builders,
            lookback_hours=self._lfg_lookback_hours)
        requested_snapshot_builders = self.m.looks_for_green.get_requested_snapshot_builders(
            builders)
        current_greenness = self._lfg_greenness(requested_snapshot_builders,
                                                lfg_lookback_hours)
        step_text_prefix = 'build used LFG, using current snapshot found by LFG'

      step_text_suffix = ': no snapshot found' if not current_greenness else ''
      pres.step_text = f'{step_text_prefix}{step_text_suffix}'

      return current_greenness

  def _waits_for_green_retryable_builders(
      self, cq_run: build_pb2.Build,
      outstanding_failure_builders: List[str]) -> List[str]:
    """Returns the builders which failed with a ToT issue that is now resolved.

    Args:
      cq_run: The CQ run to analyze.
      outstanding_failure_builders: The names of the builders with outstanding
          failures.
    """
    retryable_builders = []

    # Exit early if there are no outstanding build failures.
    if not outstanding_failure_builders:
      return retryable_builders

    if not self.is_experimental_feature_enabled(
        EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN, cq_run):
      return retryable_builders

    # If we did not find a green snapshot, return early.
    cq_retry_snapshot = self._cq_retry_snapshot(cq_run,
                                                outstanding_failure_builders)
    if not cq_retry_snapshot:
      return retryable_builders

    now_green_builders = self._get_now_green_builders(cq_run, cq_retry_snapshot)
    # now_green_builders are snapshot builders, but unsucessful_builders are
    # cq builders. Convert them with _snapshot_builder when matching them.
    now_green_retryable_builders = [
        b for b in outstanding_failure_builders
        if self.m.naming.get_snapshot_builder_name(b) in now_green_builders
    ]
    if now_green_retryable_builders:
      self._experimental_retries[cq_run.id].add(
          EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN)
    self.per_build_stats[
        cq_run.
        id].wait_for_green_stats.retryable_builders = now_green_retryable_builders
    retryable_builders.extend(now_green_retryable_builders)

    # Some CQ builders do not have snapshot equivalents (e.g. postsubmit
    # testing for the buildtest builders runs in an informational workflow).
    # As a workaround to prevent this missing data from blocking retries, if
    # there are builders that are now retryable, assume that the ones
    # without greenness reported are also retryable.
    #
    # TODO(b/299561567): See if we can address this.
    if now_green_retryable_builders:
      no_snapshot_data_builders = [
          b for b in outstanding_failure_builders
          if self.m.naming.get_snapshot_builder_name(b) not in
          cq_retry_snapshot.builder_greenness
      ]
      self.per_build_stats[
          cq_run.
          id].wait_for_green_stats.no_snapshot_data_retryable_builders = no_snapshot_data_builders
      retryable_builders.extend(no_snapshot_data_builders)

    return retryable_builders

  def analyze_test_results(
      self, cq_run: build_pb2.Build) -> Tuple[List[str], List[str], List[str]]:
    """Returns a list of test suite names grouped by retryable status.

    Args:
      cq_run: The cq-orchestrator for which to analyze the test results.

    Returns:
      A tuple containing 3 lists of test suite names grouped by whether the
          suite was successful, failed but is retryable, or failed and is not
          retryable.
    """
    with self.m.step.nest('analyzing test results') as pres:

      output_dict = json_format.MessageToDict(cq_run.output.properties)
      test_summary = output_dict.get('test_summary', [])
      # If a suite is exonerated, it does not always get reflected in the
      # test_summary, but does get added to passed_tests.
      # TODO(b/306475860): Reflect exonerations on the test_summary.
      previously_passed_suites = (
          cq_run.output.properties.get_or_create_list(PASSED_TESTS_KEY))

      successful_test_suite_names = []
      retryable_test_suite_names = []
      outstanding_failure_test_suite_names = []

      # Failures on test suites that are no longer blocking CQ submission are now
      # retryable.
      active_cq_verifiers = self._submission_blocking_builders(cq_run)
      for t in test_summary:
        name = t.get('name')
        status = t.get('status')
        critical = t.get('critical')
        builder_name = t.get('builder_name')
        revision = t.get('revision')

        if (status == 'SUCCESS' or not critical or
            name in previously_passed_suites):
          successful_test_suite_names.append(name)
        elif builder_name not in active_cq_verifiers:
          retryable_test_suite_names.append(name)
        elif revision and self._is_broken_until_updated(builder_name, revision):
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

  def _is_broken_until_updated(self, builder: str, revision: str) -> bool:
    """Returns whether the specified builder has an updated broken_until.

    Args:
      builder: The builder name for which to analyze broken_until for.
      revision: The revision used by the builder.
  """
    config = self.m.cros_infra_config.get_builder_config(builder)
    broken_until_revision = config.general.broken_until
    return self.m.cros_history.is_build_broken(revision, broken_until_revision)

  def _lfg_greenness(self, builders: List[str],
                     lookback_hours: float) -> Optional[Snapshot]:
    """Find the current green snapshot, as defined by looks for green.

    Args:
      builders: The list of builders to consider when determining aggregate
        greenness.
      lookback_hours: The number of hours to lookback when finding a green
        snapshot.

    Returns:
      A green snapshot, if found.
    """
    return self.m.looks_for_green.find_green_snapshot(
        # The staging auto retrier will still look at prod CQ runs, so it must
        # lookup greenness on the prod snapshot-orchestrator.
        bucket='postsubmit',
        builder='snapshot-orchestrator',
        requested_snapshot_builders=builders,
        lookback_hours=lookback_hours,
    )

  @functools.cached_property
  def _latest_greenness(self) -> Optional[Snapshot]:
    """Find the latest scored snapshot.

    Note that this property is cached because we assume an auto-retrier run is
    relatively short, and thus using the same latest snapshot for every retry
    candidate is ok. In addition, more straightforward for all candidates to get
    the same latest snapshot, instead of later calls potentially returning a
    different snapshot.
    """
    return self.m.looks_for_green.get_latest_snapshot_greenness(
        # The staging auto retrier will still look at prod CQ runs, so it must
        # lookup greenness on the prod snapshot-orchestrator.
        bucket='postsubmit',
        builder='snapshot-orchestrator',
    )

  def _get_now_green_builders(self, cq_run: build_pb2.Build,
                              cq_retry_snapshot: Snapshot) -> List[str]:
    """Returns builders that failed on cq_run's snapshot and are now passing at ToT.

    This function first finds the greenness for the snapshot that cq_run ran on
    and collects non-green builders. The function then finds the green snapshot
    (as defined by looks-for-green) and returns any builders that failed on
    cq_run's snapshot and are now green.

    Note that it is possible a builder failed on cq_run's snapshot, but didn't
    actually fail on cq_run; in this case, the builder is still returned (if it
    is green on the found snapshot-orchestrator).

    Args:
      The CQ run for which to get now-green builders.

    Returns:
      The names of the builders that are now green. Note that these are
        snapshot builders.
    """
    with self.m.step.nest('get now green builders') as pres:
      now_green_builders = []
      failed_on_snapshot_builders = self._failed_on_snapshot_builders(cq_run)
      if not failed_on_snapshot_builders:
        return now_green_builders

      pres.logs['failed on snapshot builders'] = failed_on_snapshot_builders
      self.per_build_stats[
          cq_run.id].wait_for_green_stats.failed_builders_in_snapshot = list(
              failed_on_snapshot_builders)

      greenness = cq_retry_snapshot.builder_greenness
      for builder in failed_on_snapshot_builders:
        if builder in greenness and greenness[builder].build_metric == 100:
          now_green_builders.append(builder)

      pres.logs['now green builders'] = now_green_builders
      self.per_build_stats[
          cq_run
          .id].wait_for_green_stats.now_green_builders = now_green_builders

      return now_green_builders

  def publish_per_build_stats(self):
    """Write PerBuildStats to an output property.

    PerBuildStats are logged for each build passed to
    analyze_build_failures. This function should be called after every call to
    analyze_build_failures is complete, to publish the stats to an output
    property.

    To make SQL analysis easier, this function converts per_build_stats from a
    map to a list and adds a new field 'build_id'. This is done because
    iterating a JSON object is less convinient than a list in most SQL dialects.
    build_id is a str to avoid integer trunctation.
    """
    self.m.easy.set_properties_step(per_build_stats=[{
        'build_id': str(k),
        **dataclasses.asdict(v)
    } for k, v in self.per_build_stats.items()])

  def _get_snapshot_builder_greenness_dict(
      self, snapshot_commit_id: str) -> Optional[collections.OrderedDict]:
    """Returns the builder greenness dict for the given snapshot commit.

    Since this value is cached it is possible that the greenness isn't published
    when it is first looked up. In that case later calls to get greenness for that
    snapshot will also return None.

    Args:
      snapshot_commit_id: The commit for which to return builder greenness.

    Returns:
      An ordered dict mapping builder -> Greenness message as a dict. Dict will
          be empty if no greenness is found.
    """
    with self.m.step.nest(
        f'get greenness for commit {snapshot_commit_id}') as pres:
      if snapshot_commit_id not in self._snapshot_greenness_cache:
        self._snapshot_greenness_cache[
            snapshot_commit_id] = self.m.buildbucket_stats.get_snapshot_greenness(
                snapshot_commit_id,
                pres,
                # The staging auto retrier will still look at prod CQ runs, so it must
                # lookup greenness on the prod snapshot-orchestrator.
                bucket='postsubmit',
                builder='snapshot-orchestrator',
                retries=0,
            )
      return self._snapshot_greenness_cache[snapshot_commit_id]

  def _failed_on_snapshot_builders(
      self, cq_run: build_pb2.Build) -> Optional[List[str]]:
    """Returns builders that failed on cq_run's snapshot.

    This function finds the greenness for the snapshot that cq_run ran on
    and collects non-green builders.

    Args:
      The CQ run for which to get failed builders.

    Returns:
      The names of the builders that failed on the snapshot or None if the
          snapshot greenness was not found.
    """
    commit = cq_run.output.gitiles_commit.id
    builder_to_greenness = self._get_snapshot_builder_greenness_dict(commit)

    if len(builder_to_greenness) == 0:
      return None

    self.per_build_stats[
        cq_run.id].wait_for_green_stats.total_builders_in_snapshot = len(
            builder_to_greenness)

    non_green_builders = [
        b for b, g in builder_to_greenness.items() if g.build_metric < 100
    ]
    return non_green_builders

  def _get_sdk_failures(self, cq_run: build_pb2.Build) -> List[str]:
    """Returns the names of builders that have SDK failures.

    Finds the failed child builders of cq_run and filters for SDK failures.
    """
    with self.m.step.nest('get sdk failures'):
      failed_child_builds = self._get_failed_child_builds(
          cq_run, fields=['builder', 'status', 'summary_markdown'])
      return [
          b.builder.builder
          for b in failed_child_builds
          if self._build_had_sdk_failure(b)
      ]

  def _get_failed_child_builds(
      self, cq_run: build_pb2.Build,
      fields: Optional[List[str]] = None) -> List[build_pb2.Build]:
    """Fetches the failed child builds in cq_run from Buildbucket.

    Args:
      cq_run: The cq-orchestrator run. Must set the 'child_build_info' output
        property.
      fields: An optional list of fields to fetch. If not set defaults to
        self.m.buildbucket.DEFAULT_FIELDS.

    Returns:
      The Build protos for the failed child builds.
    """
    output_dict = json_format.MessageToDict(cq_run.output.properties)
    child_build_info = output_dict.get('child_build_info', [])

    failed_build_ids = [
        int(cbi['id'])
        for cbi in child_build_info
        if cbi.get('status') == bb_common_pb2.Status.Name(bb_common_pb2.FAILURE)
    ]
    return self.m.buildbucket.get_multi(
        failed_build_ids, fields=fields or
        self.m.buildbucket.DEFAULT_FIELDS).values()

  def _build_had_sdk_failure(self, build: build_pb2.Build) -> bool:
    """Returns whether a build failed on a SDK step.

    Currently just checks the summary markdown.
    """
    return build.status == bb_common_pb2.FAILURE and 'chromite.api.SdkService' in build.summary_markdown

  def no_retry_footer_set(self, build):
    """Given an orchestrator's associated CLs, have any opted out via footer."""
    vals = self.m.git_footers.get_footer_values(build.input.gerrit_changes,
                                                key=RETRY_OPTIONS_FOOTER_KEY)
    if RETRY_OPTIONS_EXEMPT_VALUE in vals:
      return True
    return False

  def _get_current_cq_orchs_with_retryable_statuses(
      self) -> List[build_pb2.Build]:
    """Returns cq-orchestrators that are "current" and have a retryable status.

    "Current" means that the cq-orchestrator was the most recent cq-orchestrator
    run for the group of changes under test.

    Only the CLs' host and number are taken into account when grouping across CQ
    runs, thus allowing us to group changes across patchset revisions and filter
    out runs which correspond to outdated patchsets.
    """

    def _cl_set_hash(build: build_pb2.Build) -> FrozenSet[BasicClInfo]:
      """Returns a frozenset of BasicClInfo for the changes in the build.

      This will be used as a hash to group CQ runs that test the same set of
      GerritChanges across patchset revisions.
      """
      changes = []
      for gc in build.input.gerrit_changes:
        changes.append(BasicClInfo(gc.host, str(gc.change)))
      return frozenset(changes)

    with self.m.step.nest('query for cq-orchestrators') as pres:
      builder = builder_common_pb2.BuilderID(builder='cq-orchestrator',
                                             bucket='cq', project='chromeos')
      create_time = bb_common_pb2.TimeRange(
          start_time=timestamp_pb2.Timestamp(
              seconds=int(self.m.buildbucket.build.start_time.seconds) -
              self.lookback_seconds))
      search_predicate = builds_service_pb2.BuildPredicate(
          builder=builder, create_time=create_time,
          created_by=CHROMEOS_LUCI_AUTH_IDENTITY)

      # The builds are returned ordered from newest-to-oldest.
      fields = self.m.buildbucket.DEFAULT_FIELDS | {'tags'}
      cq_orch_runs = self.m.buildbucket.search(search_predicate, fields=fields)
      cq_orch_runs = sorted(cq_orch_runs,
                            key=lambda build: build.create_time.seconds,
                            reverse=True)

      # Get the latest cq-orchestrator run for each set of CLs.
      cl_set_to_run_mapping = {}
      for x in cq_orch_runs:

        cl_group_hash = _cl_set_hash(x)
        if cl_group_hash not in cl_set_to_run_mapping:
          cl_set_to_run_mapping[cl_group_hash] = x

      # Only return the builds with a retryable status.
      builds = [
          x for x in cl_set_to_run_mapping.values()
          if x.status in RETRYABLE_STATUSES
      ]
      pres.step_text = 'found %d builds' % len(builds)
      for b in builds:
        pres.links[b.id] = self.m.buildbucket.build_url(build_id=b.id)
      return builds

  def _has_supported_failure_mode(self, cq_orch: build_pb2.Build) -> bool:
    """Returns whether a cq-orchestrator had a supported failure mode.

    Currently supports the following failure modes:
      * child build failures and end-to-end test failures
      * infra failures (as an experimental feature)

    Other failures in the cq-orchestrator execution (e.g. merge conflict) are
    not currently retryable.

    Args:
      cq_orch: The cq-orchestrator run to consider.

    Returns:
      Whether the cq-orchestrator had a failure which may be auto-retryable.
    """
    if (self.is_experimental_feature_enabled(
        EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES, cq_orch) and
        cq_orch.status == bb_common_pb2.INFRA_FAILURE):
      self._experimental_retries[cq_orch.id].add(
          EXPERIMENTAL_FEATURE_RETRY_INFRA_FAILURES)
      return True

    return ('has_child_failures' in cq_orch.output.properties and
            cq_orch.output.properties['has_child_failures'])

  def cq_retry_candidates(self) -> List[build_pb2.Build]:
    """Returns cq-orchestrator builds which may be elegible for auto retry.

    Candidate cq-orchestrator builds must meet the following criteria:
      * The build status is in RETRYABLE_STATUSES.
      * The build is the latest cq attempt for the CLs under test.
      * The build had a supported failure mode.
      * The CLs under test are active.
    """
    with self.m.step.nest('find candidates') as presentation:
      cq_orchs = self._get_current_cq_orchs_with_retryable_statuses()
      self._filtered_build_stats['total_with_retryable_statuses'] = len(
          cq_orchs)

      with self.m.step.nest('filter out unsupported failure modes') as pres:
        unsupported_failure_mode_ids = [
            c.id for c in cq_orchs if not self._has_supported_failure_mode(c)
        ]
        cq_orchs = [
            c for c in cq_orchs if c.id not in unsupported_failure_mode_ids
        ]
        if unsupported_failure_mode_ids:
          pres.logs['filtered out runs'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(unsupported_failure_mode_ids)
          ]
        pres.step_text = f'filtered out {len(unsupported_failure_mode_ids)} run(s)'
        self._filtered_build_stats['unsupported_failure_mode'] = len(
            unsupported_failure_mode_ids)

      with self.m.step.nest('filter out closed CLs') as pres:
        failed_to_fetch_ids = set()
        non_new_ids = set()
        for c in cq_orchs:
          try:
            patch_sets = self.m.gerrit.fetch_patch_sets(
                c.input.gerrit_changes, step_name=f'fetch changes for {c.id}')
          except recipe_api.StepFailure:
            failed_to_fetch_ids.add(c.id)
            continue

          if any(p.status != 'NEW' for p in patch_sets):
            non_new_ids.add(c.id)

        ineligible_ids = non_new_ids | failed_to_fetch_ids
        cq_orchs = [c for c in cq_orchs if c.id not in ineligible_ids]
        pres.step_text = f'filtered out {len(ineligible_ids)} run(s)'
        if failed_to_fetch_ids:
          pres.logs['failed to fetch from Gerrit'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(failed_to_fetch_ids)
          ]
        if non_new_ids:
          pres.logs['non_new'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(non_new_ids)
          ]
        self._filtered_build_stats.update({
            'failed_gerrit_fetch': len(failed_to_fetch_ids),
            'non_new': len(non_new_ids),
        })

      presentation.step_text = f'found {len(cq_orchs)} candidate(s)'
      presentation.properties[
          'filtered_build_stats'] = self._filtered_build_stats

    return cq_orchs

  def build_was_dry_run(self, build: build_pb2.Build) -> bool:
    """Returns whether the build was a dry run.

    Note this assumes the $recipe_engine/cq.runMode input property is set,
    which may not be true for some builds (e.g. manually triggered builds).

    Args:
      build: The build for which to determine whether it is a dry run.
    """
    return build.input.properties['$recipe_engine/cv'][
        'runMode'] == self.m.cv.DRY_RUN

  def _get_auto_retry_counts(self,
                             cq_orchs: List[build_pb2.Build]) -> Dict[int, int]:
    """Computes the number of times each of the candidates has been auto-retried.

    For each candidate, find its cq_equivalent_cl_group_key and query
    Buildbucket for how many auto-retry builds have already been done on this
    group. Note that any manual tries (including the initial CQ run) on this
    group will not be included. Any auto / manual tries on the same set of CLs
    but a different cq_equivalent_cl_group_key will also not be included; this
    means non-trivial changes will effectively reset the auto-retry count.

    If a candidate doesn't have the cq_equivalent_cl_group_key tag, its step
    will be set to FAILURE status (this is unexpected), but an exception isn't
    raised so that this candidate won't block all other retries.

    Args:
      cq_orchs: The retry candidates.

    Returns:
      A map from orchestrator id to the auto-retry count for that orch's
        cq_equivalent_cl_group_key. If a orch didn't have a
        cq_equivalent_cl_group_key (this is unexpected) it won't be included in
        the map.
    """
    auto_retry_counts = {}
    for b in cq_orchs:
      with self.m.step.nest(f'find previous auto-retries for {b.id}') as pres:
        group_key = self.m.cros_tags.get_single_value(
            'cq_equivalent_cl_group_key', b.tags)
        if group_key:
          builds_found = self.m.buildbucket.search(
              builds_service_pb2.BuildPredicate(
                  builder=builder_common_pb2.BuilderID(
                      builder='cq-orchestrator', bucket='cq',
                      project='chromeos'), tags=self.m.buildbucket.tags(
                          cq_equivalent_cl_group_key=group_key,
                          cq_triggerer=self._retry_service_account,
                      )),
          )
          auto_retry_counts[b.id] = len(builds_found)
          pres.step_text = f'found {len(builds_found)} total auto-retries for build {b.id}'
        else:
          pres.status = self.m.step.FAILURE
          pres.step_text = f'cq_equivalent_cl_group_key not found for {b.id}'

    return auto_retry_counts

  def _build_is_multi_retry_eligible(self, cq_orch: build_pb2.Build,
                                     auto_retry_count: int) -> bool:
    """Return whether the build is eligible for multiple auto-retries.

    Evaluates whether the build is eligible based on self._multi_retry_config.

    Args:
      cq_orch: The retry candidate.
      auto_retry_count: The number of times the build has already been
        auto-retried. If this build was the original CQ run, this should be 0,
        if this build was the first auto-retry, it should be 1, etc.
    """
    with self.m.step.nest(
        f'determine if {cq_orch.id} is multi-retry eligible') as pres:
      # If the count has reached max_retries, never retry.
      if auto_retry_count >= self._multi_retry_config.max_retries:
        pres.step_text = 'ineligible: count ({auto_retry_count}) >= max_retries ({self._multi_retry_config.max_retries})'
        return False

      # If there haven't been any auto-retries yet, always retry.
      if not auto_retry_count:
        pres.step_text = 'eligible: no auto-retries yet'
        return True

      # Don't do a second retry if it is a fault-attributed candidate.
      # TODO(b/307333381): Remove this workaround and configure multi-retry
      # scenarios in a better way.
      if EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES in self._experimental_retries[
          cq_orch.id]:
        pres.step_text = 'ineligible: experimental fault-attributed candidates not eligible for multi-retry'
        return False

      # If using a constant backoff strategy, retry if it has been
      # constant_backoff_duration since the candidate finished.
      if self._multi_retry_config.HasField('constant_backoff_duration'):
        seconds_since_candidate = self.m.time.time() - cq_orch.end_time.seconds
        eligible = seconds_since_candidate > self._multi_retry_config.constant_backoff_duration.seconds

        step_text = f'{seconds_since_candidate}s since last candidate (constant_backoff_duration is {self._multi_retry_config.constant_backoff_duration.seconds}s)'
        pres.step_text = f'eligible: {step_text}' if eligible else f'ineligible: {step_text}'

        return (self.m.time.time() - cq_orch.end_time.seconds >
                self._multi_retry_config.constant_backoff_duration.seconds)

      unimplemented_backoff_strategy = self._multi_retry_config.WhichOneof(
          'backoff_strategy')  # pragma: nocover
      raise ValueError(  # pragma: nocover
          f'unimplemented backoff_strategy {unimplemented_backoff_strategy}')

  def filter_retry_candidates(
      self, cq_orchs: List[build_pb2.Build]) -> List[build_pb2.Build]:
    """Returns cq-orchestrator builds which meet the retry criteria.

    cq-orchestrator builds must meet the following criteria:
      * No CL tested in the build opted-out via footer.
      # TODO(b/305741866): Define more elaborate retry limits.
      * The build was not last triggered by our service account.
      * All CLs in the build are mergeable (as defined by the Gerrit API's
        GetMergeable) and ready for submission.
    """

    with self.m.step.nest('filter candidates') as presentation:

      with self.m.step.nest('filter out merge conflicts') as pres:
        non_mergeable_ids = set()
        for c in cq_orchs:
          for change in c.input.gerrit_changes:
            try:
              if not self.m.gerrit.get_change_mergeable(
                  change.change, change.host, change.patchset):
                non_mergeable_ids.add(c.id)
                break
            except recipe_api.StepFailure as e:
              non_mergeable_ids.add(c.id)
              self.m.deferrals.defer_exception(e)
              break

        cq_orchs = [c for c in cq_orchs if c.id not in non_mergeable_ids]
        if non_mergeable_ids:
          pres.logs['non_mergeable'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(non_mergeable_ids)
          ]
        pres.step_text = f'filtered out {len(non_mergeable_ids)} run(s)'
        self._filtered_build_stats['non_mergeable'] = len(non_mergeable_ids)
        for bid in non_mergeable_ids:
          self.per_build_stats[bid].filter_reasons.append('non_mergeable')

      with self.m.step.nest('filter multi-retry eligible runs') as pres:
        auto_retry_counts = self._get_auto_retry_counts(cq_orchs)
        pres.logs['auto retry counts'] = [
            f'go/bbid/{id} -> {count}'
            for id, count in auto_retry_counts.items()
        ]
        non_multi_retry_eligible = [
            c.id for c in cq_orchs if
            # It is possible, but unexpected, that a candidate doesn't have an
            # auto-retry count because it didn't have the
            # cq_equivalent_cl_group_key tag. In this case filter it but don't
            # crash the build.
            not (c.id in auto_retry_counts and self
                 ._build_is_multi_retry_eligible(c, auto_retry_counts[c.id]))
        ]
        cq_orchs = [c for c in cq_orchs if c.id not in non_multi_retry_eligible]
        if non_multi_retry_eligible:
          pres.logs['filtered out runs'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(non_multi_retry_eligible)
          ]
        pres.step_text = f'filtered out {len(non_multi_retry_eligible)} run(s)'
        self._filtered_build_stats['non_multi_retry_eligible'] = len(
            non_multi_retry_eligible)
        for bid in non_multi_retry_eligible:
          self.per_build_stats[bid].filter_reasons.append(
              'non_multi_retry_eligible')

      with self.m.step.nest('filter out opt-out runs') as pres:
        opt_out_ids = [c.id for c in cq_orchs if self.no_retry_footer_set(c)]
        cq_orchs = [c for c in cq_orchs if c.id not in opt_out_ids]
        pres.step_text = f'filtered out {len(opt_out_ids)} run(s)'
        if opt_out_ids:
          pres.logs['filtered out runs'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(opt_out_ids)
          ]
        self._filtered_build_stats['opt_out'] = len(opt_out_ids)
        for bid in opt_out_ids:
          self.per_build_stats[bid].filter_reasons.append('opt_out')

      with self.m.step.nest('filter out unmet CL requirements') as pres:
        non_submittable_ids, wip_ids, non_latest_patch_set_ids, unresolved_comment_ids, removed_label_ids, negative_labels_ids = set(
        ), set(), set(), set(), set(), set()

        for c in cq_orchs:
          patch_sets = self.m.gerrit.fetch_patch_sets(
              c.input.gerrit_changes, include_submittable=True,
              include_messages=True, include_detailed_labels=True,
              step_name=f'fetch changes for {c.id}')

          # Filters which apply to all CQ modes.
          if not self._was_cv_active(c.id, patch_sets):
            removed_label_ids.add(c.id)
            # If the CV was not active, the build could have been run manually.
            # Manually launched builds do not have the `$recipe_engine/cq` property,
            # so we do not want to check for them what type it was (DryRun/FullRun).
            continue
          non_latest_patch_set_ids.update(
              {c.id for p in patch_sets if not p.is_latest_patch_set()})

          # Filters which only apply to dry-runs.
          if self.build_was_dry_run(c):
            # If the build was a dry-run, retry even if it is not "submittable"
            # as long as there are not "negative" votes on the CL.
            negative_labels_ids = {
                c.id
                for p in patch_sets
                if p.has_label_vote('Code-Review', -1) or p.has_label_vote(
                    'Code-Review', -2) or p.has_label_vote('Verified', -1)
            }

          # Filters which only apply to full runs.
          else:
            wip_ids.update({c.id for p in patch_sets if p.work_in_progress})
            unresolved_comment_ids.update(
                {c.id for p in patch_sets if p.unresolved_comment_count})
            non_submittable_ids.update(
                {c.id for p in patch_sets if not p.submittable})

        ineligible_ids = (
            non_submittable_ids | wip_ids
            | non_latest_patch_set_ids
            | unresolved_comment_ids | removed_label_ids | negative_labels_ids)
        cq_orchs = [c for c in cq_orchs if c.id not in ineligible_ids]
        pres.step_text = f'filtered out {len(ineligible_ids)} run(s)'
        if non_submittable_ids:
          pres.logs['non_submittable'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(non_submittable_ids)
          ]
        for bid in non_submittable_ids:
          self.per_build_stats[bid].filter_reasons.append('non_submittable')
        if wip_ids:
          pres.logs['wip'] = [
              self.m.buildbucket.build_url(build_id=x) for x in sorted(wip_ids)
          ]
        for bid in wip_ids:
          self.per_build_stats[bid].filter_reasons.append('wip')
        if non_latest_patch_set_ids:
          pres.logs['non_latest_patch_set'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(non_latest_patch_set_ids)
          ]
        for bid in non_latest_patch_set_ids:
          self.per_build_stats[bid].filter_reasons.append(
              'non_latest_patch_set')
        if unresolved_comment_ids:
          pres.logs['unresolved_comments'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(unresolved_comment_ids)
          ]
        for bid in unresolved_comment_ids:
          self.per_build_stats[bid].filter_reasons.append('unresolved_comments')
        if removed_label_ids:
          pres.logs['removed_label'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(removed_label_ids)
          ]
        for bid in removed_label_ids:
          self.per_build_stats[bid].filter_reasons.append('removed_label')
        if negative_labels_ids:
          pres.logs['negative_labels'] = [
              self.m.buildbucket.build_url(build_id=x)
              for x in sorted(negative_labels_ids)
          ]
        for bid in negative_labels_ids:
          self.per_build_stats[bid].filter_reasons.append('negative_labels')

        self._filtered_build_stats.update({
            'non_submittable': len(non_submittable_ids),
            'wip': len(wip_ids),
            'non_latest_patch_set': len(non_latest_patch_set_ids),
            'unresolved_comments': len(unresolved_comment_ids),
            'removed_label': len(removed_label_ids),
            'negative_labels': len(negative_labels_ids),
        })

      presentation.properties[
          'filtered_build_stats'] = self._filtered_build_stats
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
      pres.logs['updated failed test stats'] = str(updated_stats)

      newly_exonerated_stats, outstanding_failure_stats = _categorize_stats(
          updated_stats)

      pres.step_text = '%d previously exonerated, %d newly exonerated, %d outstanding' % (
          len(previously_exonerated_stats), len(newly_exonerated_stats),
          len(outstanding_failure_stats))
      pres.logs['previously_exonerated_tests'] = sorted(
          [x.test_id for x in previously_exonerated_stats])
      pres.logs['newly_exonerated_tests'] = sorted(
          [x.test_id for x in newly_exonerated_stats])
      pres.logs['outstanding_failure_tests'] = sorted(
          [x.test_id for x in outstanding_failure_stats])

      return (previously_exonerated_stats, newly_exonerated_stats,
              outstanding_failure_stats)

  def _is_hw_result_attributed(
      self, result: SkylabResult,
      fault_attribution_stats: CqTestFailureFaultAttributionStats) -> bool:
    """Returns true if result can be attributed to a matching snapshot failure.

    Result is considered attributed if all of its failed test cases have the
    MATCHING_FAILURE_FOUND attribution for at least one build target. Note that
    this does not need to be the same build target, e.g. if test1 fails on
    targetA but has a matching failure on targetB, test1 is still considered
    attributed.

    If result was successful, non-critical, or doesn't have child results,
    returns false.
    """
    result_title = self.m.naming.get_skylab_result_title(result)
    with self.m.step.nest(f'determine attribution for {result_title}') as pres:
      if (result.status == bb_common_pb2.SUCCESS or
          not result.task.test.common.critical.value or
          not result.child_results):
        pres.step_text = 'result not eligible for attribution'
        return False

      attributed_test_failures: Set[str] = set()

      for test_failure_attribution in fault_attribution_stats.test_failure_attributions:
        for fault_attribution in test_failure_attribution.fault_attributes:
          if fault_attribution.snapshot_comparison_fault_attribution == CqFailureAttribute.MATCHING_FAILURE_FOUND:
            attributed_test_failures.add(fault_attribution.test_name)

      for child_result in result.child_results:
        if child_result.state.life_cycle != TaskState.LIFE_CYCLE_COMPLETED:
          pres.step_text = 'cannot attribute results that are not LIFE_CYCLE_COMPLETED'
          return False

        for test_case in child_result.test_cases:
          if test_case.verdict == TaskState.VERDICT_NO_VERDICT:
            pres.step_text = 'cannot attribute results containing NO_VERDICT'
            return False

          if test_case.verdict in (
              TaskState.VERDICT_UNSPECIFIED, TaskState.VERDICT_FAILED
          ) and test_case.name not in attributed_test_failures:
            pres.step_text = f'{test_case.name} not attributed'
            return False

      pres.step_text = 'all failures attributed'
      return True

  def _get_hw_test_results(self, cq_run: build_pb2.Build) -> List[SkylabResult]:
    """Gets the SkylabResults for a given CQ run.

    Parses the test_summary and test_tasks output properties of the CQ run and
    then fetches and parses the output properties of the skylab builders.
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
      board = test_summary_dict['board']
      model = test_summary_dict['model']
      suite = display_name.split('.')[-1]
      hw_test = HwTestCfg.HwTest(
          common=TestSuiteCommon(display_name=display_name,
                                 critical={'value': critical}),
          suite=suite,
          skylab_model=model,
          skylab_board=board,
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

    # Get the CTP builds.
    output_dict = json_format.MessageToDict(cq_run.output.properties)
    test_summary = output_dict.get('test_summary', [])
    test_tasks = output_dict.get('test_tasks', {})
    skylab_builder_ids = [
        int(b) for b in test_tasks.get('skylab_builder_ids', [])
    ]

    hw_test_results = []
    # Exonerate HW test results.
    if len(skylab_builder_ids) > 0:
      hw_units = [
          _hw_unit(t) for t in test_summary if '.hw.' in t.get('name', '')
      ]
      hw_test_results = self.m.skylab_results.get_previous_results(
          skylab_builder_ids, hw_units)

    return hw_test_results

  def get_failure_attributed_hw_suites(
      self, cq_run: build_pb2.Build,
      already_retryable_suites: Optional[Iterable[str]] = None) -> List[str]:
    """Returns a list of suites that can have their failures attributed.

    This method is based on the cq_fault_attributions output property of the
    CQ orchestrator, it does not do the actual attribution analysis. A suite
    is considered attributed if all of its failed test cases have the
    MATCHING_FAILURE_FOUND attribution for at least one build target. Note that
    this does not need to be the same build target, e.g. if test1 fails on
    targetA but has a matching failure on targetB, test1 is still considered
    attributed.

    Args:
      cq_run: The CQ run to check for attributed tests.
      already_retryable_suites: Suites that have already been determined to be
        retryable via other methods (e.g. the suite is now exonerated). If set,
        these suites are removed from the returned list of attributed suites.

    Returns:
      A list of suite names that have all failing tests attributed.
    """
    with self.m.step.nest('get attributed hw suites') as pres:
      if not self.is_experimental_feature_enabled(
          EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES, cq_run):
        pres.step_text = 'experimental feature not enabled'
        return []

      output_dict = json_format.MessageToDict(cq_run.output.properties)
      fault_attribution_stats = CqTestFailureFaultAttributionStats()
      json_format.ParseDict(
          output_dict.get('cq_fault_attributions', {}), fault_attribution_stats)

      hw_test_results = self._get_hw_test_results(cq_run)
      attributed_suites = []

      pres.logs['fault attribution stats'] = json_format.MessageToJson(
          fault_attribution_stats)
      pres.logs['hw test results'] = str(hw_test_results)

      for result in hw_test_results:
        if self._is_hw_result_attributed(result, fault_attribution_stats):
          attributed_suites.append(
              self.m.naming.get_skylab_result_title(result))

      pres.step_text = f'found {len(attributed_suites)} attributed suite(s)'
      pres.logs['attributed suites'] = attributed_suites

      if already_retryable_suites:
        attributed_suites = list(
            set(attributed_suites).difference(already_retryable_suites))
        pres.logs['already retryable suites'] = already_retryable_suites
        pres.logs[
            'attributed suites (excluding already retryable)'] = attributed_suites

      if attributed_suites:
        self._experimental_retries[cq_run.id].add(
            EXPERIMENTAL_FEATURE_RETRY_ATTRIBUTED_FAILURES)

      return attributed_suites

  def _get_exonerated_hw_suites(self, cq_run: build_pb2.Build,
                                exon_configs: Dict):
    """Returns the names of newly exonerated hw test suites."""
    # Filter out suites which were previously exonerated.
    previously_passed_suites = set(
        cq_run.output.properties.get_or_create_list(PASSED_TESTS_KEY))

    hw_test_results = self._get_hw_test_results(cq_run)

    exonerated_suites = set()
    exonerated_prejob_failure_suites = set()
    for result in hw_test_results:
      suite = self.m.naming.get_skylab_result_title(result)
      if suite in previously_passed_suites:
        continue

      # Manual exoneration.
      # The excludes configs are not taken into account when doing
      # manual exoneration. The excludes configs are meant as a guardrail to
      # prevent auto-exoneration from submitting CLs which are failing critical
      # tests. Manual exoneration gives sheriffs the option over forcing these
      # tests to be exonerated.
      if self.m.exonerate.is_hw_result_exonerable(
          result, self.m.exonerate.manual_exoneration_configs,
          excludes_enabled_override=False):
        exonerated_suites.add(suite)
      # Auto exoneration.
      elif self.m.exonerate.is_hw_result_exonerable(
          result, exon_configs, excludes_enabled_override=True):
        exonerated_suites.add(suite)
      # Pre-job failure exoneration.
      elif self.m.exonerate.is_hw_result_exonerable(
          result, exon_configs, exonerate_prejob_failures=True,
          excludes_enabled_override=True):
        exonerated_prejob_failure_suites.add(suite)

    # Prejob failures are only retryable if the experimental feature is enabled.
    if self.is_experimental_feature_enabled(
        EXPERIMENTAL_FEATURE_RETRY_PREJOB_FAILURES, cq_run):
      prejob_stats = self.m.skylab_results.get_per_board_prejob_stats(
          hw_test_results)

      output_dict = json_format.MessageToDict(cq_run.output.properties)
      test_summary = output_dict.get('test_summary', [])

      for suite in exonerated_prejob_failure_suites:
        # Prejob failures can only be retried if the failure was a known flake.
        # This is determined by checking that the board that the suite ran on
        # passed the prejob steps at least once in the run.
        board = next((x['board'] for x in test_summary if x['name'] == suite))
        # TODO(b/289095330): Get the suite name from the test_summary once the
        # test_summary is updated to include it.
        suite_name = suite.split('.')[-1]
        board_prejob_stats = prejob_stats.get(board, PrejobStats())
        if board_prejob_stats.succeeded:
          exonerated_suites.add(suite)
          self._experimental_retries[cq_run.id].add(
              EXPERIMENTAL_FEATURE_RETRY_PREJOB_FAILURES)
        # The "cq-minimal" suite is run on only one shard. This makes it so that
        # prejob data on that board is limited. In this case, a successful
        # prejob on any board is sufficient.
        elif suite_name == CQ_MINIMAL_SUITE_NAME and any(
            x.succeeded for x in prejob_stats.values()):
          exonerated_suites.add(suite)
          self._experimental_retries[cq_run.id].add(
              EXPERIMENTAL_FEATURE_RETRY_PREJOB_FAILURES)

    return exonerated_suites

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

    # Exit early if the run exceeds any of the exoneration guardrails.
    override_info = self.m.exoneration_util.override_calculation(
        failed_test_stats, self.m.exonerate.overall_autoex_limit,
        self.m.exonerate.per_target_autoex_limit)
    if override_info.override_reason:
      return []

    # Generate the exoneration configs for this specific CQ run.
    exon_configs = self.m.exoneration_util.get_updated_configs(
        failed_test_stats, self.m.exonerate.manual_exoneration_configs)

    exonerated_suites = set()
    exonerated_suites.update(
        self._get_exonerated_hw_suites(cq_run, exon_configs))

    return sorted(exonerated_suites)

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
    build_link = self.m.buildbucket.build_url(host='cr-buildbucket.appspot.com',
                                              build_id=build.id)
    comment = f'The previous build ({build_link}) is being automatically retried for the following reasons:\n'
    if retryable_builders:
      comment += '- Some child builders are now retryable:'
      if len(retryable_builders) <= self.builds_comment_limit:
        comment += ', '.join(retryable_builders) + '\n'
      else:
        comment += ', '.join(
            retryable_builders[:self.builds_comment_limit]) + ',...\n'

    if retryable_test_suites:
      comment += '- Some tests are now retryable:'
      if len(retryable_test_suites) <= self.suites_comment_limit:
        comment += ', '.join(retryable_test_suites) + '\n'
      else:
        comment += ', '.join(
            retryable_test_suites[:self.suites_comment_limit]) + ',...\n'
    comment += '\nDid you notice a bug or UX issue with this retry? Please provide feedback: go/cros-auto-retry-bug.\n'
    return comment

  def _retry_build(
      self,
      build: build_pb2.Build,
      retryable_builders: List[str],
      retryable_test_suites: List[str],
  ) -> bool:
    """Retries build by voting on all of its input changes.

    Sets Commit-Queue+1 or 2 (depending on whether build was a dry run)
    on all of build's input changes. It is assumed that all other labels
    required for submission are set. Also leaves a comment explaining why the
    build was retried.

    At least one of retryable_builders and retryable_test_suites must be
    non-empty.

    Note that this method is affected by the enable_retries property on this
    module (it won't set labels or leave comments if the property is not set).

    Args:
      build: The build to retry.
      retryable_builders: Names of the child builders that are now retryable.
      retryable_test_suites: Names of the test suites that are now retryable.

    Returns:
      Whether the retry actually happened.
    """
    if not any(x for x in retryable_builders) and not any(
        x for x in retryable_test_suites):
      raise ValueError(
          'At least one builder or test suite must be given as a retry reason '
          f'for build {build.id}')

    comment = self._create_comment(build, retryable_builders,
                                   retryable_test_suites)

    with self.m.step.nest(
        f'retry build {build.id}{ " (dry_run)" if not self._enable_retries else ""}'
    ) as pres:
      pres.logs['retryable builders'] = ','.join(sorted(retryable_builders))
      pres.logs['retryable test suites'] = ','.join(
          sorted(retryable_test_suites))

      labels = {
          Label.COMMIT_QUEUE: 1 if self.build_was_dry_run(build) else 2,
      }

      patch_sets = self.m.gerrit.fetch_patch_sets(
          build.input.gerrit_changes, include_detailed_labels=True,
          step_name=f'fetch changes for {build.id}')
      if any(not ps.has_default_label_vote(Label.COMMIT_QUEUE.key)
             for ps in patch_sets):
        pres.step_text = 'Already retried by someone else.'
        self.per_build_stats[build.id].filter_reasons.append('retried_by_user')
        return False

      if not self._enable_retries:
        pres.step_text = f'would have set labels { {str(k): v for k, v in labels.items()} }'
        return False

      for gc in build.input.gerrit_changes:
        self.m.gerrit.set_change_labels_remote(gc, labels)
        self.m.gerrit.add_change_comment_remote(gc, comment)

      return True

  def retry_builds(
      self, retryable_runs: List[Tuple[build_pb2.Build, RetryDetails]]
  ) -> Tuple[List[build_pb2.Build], List[Exception]]:
    """Performs retry on retryable builds.

    Args:
      retryable_runs: List of tuples with failed build and retry details.

    Returns:
      A tuple with a retried (old) builds and a list with exceptions.
    """
    retried_runs = []
    already_retried = []
    exceptions = []
    for b, details in retryable_runs:
      # There should be at least one retryable builder or test suite at this
      # point, because cq_retry_candidates only returns builds with at least one
      # fatal failure, and there are no more outstanding failures for the build.
      try:
        if self._retry_build(b, details.retryable_builders,
                             details.retryable_test_suites):
          retried_runs.append(b)
        elif self._enable_retries:
          already_retried.append(b)
      except ValueError as e:
        exceptions.append(e)

      details.retry_age_seconds = int(
          self.m.time.ms_since_epoch() / 1000) - b.end_time.seconds

    self._filtered_build_stats.update({
        'already_retried': len(already_retried),
    })
    self.m.easy.set_properties_step(
        filtered_build_stats=self._filtered_build_stats)

    return retried_runs, exceptions

  def _was_cv_active(self, build_id: int, patch_sets: List[PatchSet]) -> bool:
    """Check if the CV was active when the given build failed.

    Checks if CV was active when a build failed by checking for a message from
    CV which states that a build with the given build id failed.

    When CQ labels are removed from a CL, the CQ builds are not automatically
    canceled. Therefore these builds will show up in our queries but should not
    be retried.

    Args:
      build_id: The CQ builder of interest.
      patch_sets: The list with PatchSet for which to check if CV noted the
        given build failure.

    Returns:
      Whether CV was active on all the patchsets when the build failed.
    """
    for p in patch_sets:
      cv_account_id = self.m.gerrit.get_account_id(
          self._chromeos_luci_service_account, p.host)
      # If CV is still active when a CQ build fails it will post a message which
      # links the build failure.
      if not any(
          str(build_id) in m['message'] and
          m.get('author', {}).get('_account_id') == cv_account_id
          for m in p.messages):
        return False

    return True

  def _get_not_cl_affected_package_failure_builders(
      self, cq_run: build_pb2.Build,
      outstanding_failure_builders: List[str]) -> List[Optional[str]]:
    """Returns builders which had unrelated package failures.

    Args:
      cq_run: The CQ run to analyze.
      outstanding_failure_builders: The names of the builders with outstanding
          failures.
    """
    output_dict = json_format.MessageToDict(cq_run.output.properties)
    child_build_info = output_dict.get('child_build_info', [])

    builders = []
    for cbi in child_build_info:
      if cbi['builder']['builder'] not in outstanding_failure_builders:
        continue
      package_failures = [
          json_format.ParseDict(x, PackageFailure())
          for x in cbi.get('package_failures', [])
      ]
      if not package_failures:
        continue
      if all(not x.affected_by_changes for x in package_failures):
        builders.append(cbi['builder']['builder'])

    return builders
