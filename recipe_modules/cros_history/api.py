# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module to use build history to avoid redundant builds."""

import base64
import datetime
import functools
from typing import List, Iterable, Optional, Set, Tuple
import zlib

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from PB.chromite.api.packages import UprevPackagesResponse
from PB.chromiumos import common as chromiumos_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import (common as bb_common_pb2)
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult
from RECIPE_MODULES.chromeos.skylab_results.structs import UnitHwTest
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

PASSED_TESTS_KEY = 'passed_tests'
UPREV_RESPONSE_KEY = 'compressed_uprev_response'
SNAPSHOT_BUCKET = 'postsubmit'
TEST_SUMMARY_KEY = 'test_summary'
TEST_TASKS_KEY = 'test_tasks'
TERMINAL_STATUSES = [
    bb_common_pb2.SUCCESS,
    bb_common_pb2.FAILURE,
    bb_common_pb2.INFRA_FAILURE,
    bb_common_pb2.CANCELED,
]


class CrosHistoryApi(recipe_api.RecipeApi):
  """A module to use build history to avoid redundant builds."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._use_group_key = not properties.disable_group_key
    self._lookback_seconds = properties.lookback_seconds or 5 * 24 * 60 * 60
    self._passed_tests = None
    self._cached_annealing_builds = {}

  @property
  def start_time_in_seconds(self) -> float:
    """Generate start time in seconds."""
    return self.m.time.time() - self._lookback_seconds

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=30))
  def get_annealing_from_snapshot(
      self, snapshot_id: str) -> Optional[build_pb2.Build]:
    """Find the annealing build that created snapshot with given ID.

    Args:
      snapshot_id: Manifest snapshot commit ID.

    Returns:
      If an Annealing build is found, then a proto message of that build.
      Otherwise, None.
    """
    if snapshot_id in self._cached_annealing_builds:
      return self._cached_annealing_builds[snapshot_id]
    tags = self.m.cros_tags.tags(published_snapshot_id=snapshot_id)
    # Not searching based on builder because we want to find both Annealing
    # staging-Annealing builds. Tags are indexed by Buildbucket so this
    # should be fast.
    predicate = builds_service_pb2.BuildPredicate(tags=tags)
    predicate.builder.project = 'chromeos'
    builds = self.m.buildbucket.search(
        predicate, limit=1, url_title_fn=self.m.naming.get_build_title)
    if not builds:
      return None
    assert len(builds) == 1
    self._cached_annealing_builds[snapshot_id] = builds[0]
    return builds[0]

  def is_build_broken(self, build_snapshot: str,
                      broken_until_snapshot: str) -> Optional[bool]:
    """Determine whether the build to be recycled is broken.

    Args:
      build_snapshot: GitliesCommit id of the build to be recycled.
      broken_until_snapshot: SHA of the manifest snapshot from broken_until config.

    Returns:
      Whether to recycle the build.
    """
    with self.m.step.nest('check if build is broken'):
      broken_until_annealing = self.get_annealing_from_snapshot(
          broken_until_snapshot)
      build_annealing = self.get_annealing_from_snapshot(build_snapshot)
      # If we can't find the annealing builds, don't reuse.
      if not build_annealing or not broken_until_annealing:
        return True
      return (broken_until_annealing.end_time.seconds
              >= build_annealing.end_time.seconds)

  def hours_since_breakage(self, broken_until: str) -> Optional[int]:
    """Determine how long it has been since the tree was fixed.

    Args:
      broken_until: manifest snapshot SHA from builderconfig.

    Returns:
      hours since broken_until snapshot creation.
    """
    annealing = self.get_annealing_from_snapshot(broken_until)
    if not annealing:
      return None
    return int((self.m.time.time() - annealing.end_time.seconds) / (60 * 60))

  @staticmethod
  def get_upreved_pkgs(
      annealing_build: build_pb2.Build
  ) -> List[chromiumos_common_pb2.PackageInfo]:
    """Retrieve the packages upreved by the annealing build.

    Args:
      annealing_build: The Annealing build in question.

    Returns:
      List of upreved packages.
    """
    build_output = json_format.MessageToDict(annealing_build.output.properties)
    compressed_response = build_output.get(UPREV_RESPONSE_KEY, '')
    response_str = zlib.decompress(base64.b64decode(compressed_response))
    uprev_response = UprevPackagesResponse.FromString(response_str)
    return uprev_response.packages

  def get_passed_builds(
      self, tags: Optional[List[bb_common_pb2.StringPair]] = None
  ) -> List[build_pb2.Build]:
    """Retrieve passed builds with the same patches as current build.

    Args:
      tags: Get builds with these tags.

    Returns:
      Passed builds with the most recent build per builder.
    """
    with self.m.step.nest('get change build history') as presentation:
      build = self.m.buildbucket.build
      latest_passed_builds = []
      # Start with cq-orchestrator so we don't add it to the result.
      current_builder_id = build.builder
      passed_builders = set([current_builder_id.builder])
      patches = build.input.gerrit_changes
      # Search across all buckets as builders have been moved to their own individual buckets.
      builder_shell = builder_common_pb2.BuilderID(
          project=current_builder_id.project)
      all_passed_builds = self._get_patch_history(
          patches, builder=builder_shell, statuses=[bb_common_pb2.SUCCESS],
          tags=tags)
      all_passed_builds.sort(key=lambda build: build.start_time.seconds,
                             reverse=True)
      for build in all_passed_builds:
        if build.builder.builder not in passed_builders:
          passed_builders.add(build.builder.builder)
          latest_passed_builds.append(build)

      presentation.step_text = ('some builds already completed'
                                if latest_passed_builds else
                                'found no completed builds')
      latest_passed_builds.sort(key=lambda build: build.builder.builder)
      for build in latest_passed_builds:
        title = self.m.naming.get_build_title(build)
        url = self.m.buildbucket.build_url(build_id=build.id)
        presentation.links[title] = url

      return latest_passed_builds

  def get_test_failure_builders(self) -> Set[str]:
    """Get builders with the given patches that failed tests in the last run.

    Returns:
      Names of builders with HW or VM testing failures, if any.
    """
    current_build = self.m.buildbucket.build
    past_builds = self.get_matching_builds(current_build,
                                           statuses=TERMINAL_STATUSES)
    if not past_builds:
      return set()
    past_builds.sort(key=lambda build: build.create_time.seconds, reverse=True)

    # Read the test_summary from the most recent CQ run which set it.
    test_summary = []
    for build in past_builds:
      build_output = json_format.MessageToDict(build.output.properties)

      if TEST_SUMMARY_KEY in build_output:
        test_summary = build_output.get(TEST_SUMMARY_KEY)
        break

    critical_failed_test_names = [
        test.get('name')
        for test in test_summary
        if test.get('status') == 'FAILURE' and test.get('critical')
    ]
    # Test names are of the form `{builder_name}.{test_type}.{suite_name}`.
    return {test.split('.')[0] for test in critical_failed_test_names}

  def get_passed_tests(self) -> Set[str]:
    """Find all tests that have passed with the given patches.

    Returns:
      Names of passed tests, if any.
    """
    if self._passed_tests is not None:
      return self._passed_tests

    with self.m.step.nest('get change test history') as presentation:
      current_build = self.m.buildbucket.build
      past_builds = self.get_matching_builds(current_build,
                                             statuses=TERMINAL_STATUSES)

      all_passed_tests = set()
      for build in past_builds:
        build_output = json_format.MessageToDict(build.output.properties)
        passed_tests = build_output.get(PASSED_TESTS_KEY, [])
        all_passed_tests |= set(passed_tests)

      presentation.step_text = ('some tests already passed' if all_passed_tests
                                else 'found no previously passed tests')
      if all_passed_tests:
        presentation.logs['list of passed tests'] = sorted(all_passed_tests)

      self._passed_tests = all_passed_tests
      return self._passed_tests

  def get_previous_test_task_ids(self) -> Tuple[List[int], List[int]]:
    """Get the task ids of the latest test invocations.

    Returns:
      A tuple (vm_build_ids, hw_build_ids), where:
      * vm_build_ids is a list of buildbucket IDs for all Tast VM tests for the
        latest invocation of this builder with the same set of Gerrit changes.
      * hw_build_ids is a list of buildbucket IDs for all Skylab tests for the
        latest invocation of this builder with the same set of Gerrit changes.
    """
    current_build = self.m.buildbucket.build
    past_builds = self.get_matching_builds(current_build,
                                           statuses=TERMINAL_STATUSES)
    if not past_builds:
      return [], []

    # TODO(b/271938042): Iterate through the list until we find a build that
    # does has the TEST_TASKS_KEY. This is useful in case the previous build was
    # terminated unexpectedly before scheduling tests.
    last_build = past_builds[0]
    build_output = json_format.MessageToDict(last_build.output.properties)
    test_tasks = build_output.get(TEST_TASKS_KEY)
    if not test_tasks:
      return [], []

    vm_build_ids = [
        int(b) for b in test_tasks.get('tast_vm_tests_builder_ids', [])
    ]
    hw_build_ids = [int(b) for b in test_tasks.get('skylab_builder_ids', [])]
    return vm_build_ids, hw_build_ids

  def get_previous_test_results(
      self, test_plan: GenerateTestPlanResponse
  ) -> Tuple[List[build_pb2.Build], List[SkylabResult]]:
    """Get the tests from the previous run.

    Args:
      test_plan: The test plan which contains the tests for which to retrieve
      the results from previous runs.

    Returns:
      A tuple containing the list of the previous VM test builds and the list
      of the previous HW test results.
    """

    with self.m.step.nest('get previous test results'):
      vm_build_ids, hw_build_ids = self.get_previous_test_task_ids()
      if not (vm_build_ids or hw_build_ids):
        return [], []

      vm_test_results = self.m.buildbucket.get_multi(
          vm_build_ids,
          step_name='get tast vm tests from previous run').values()

      hw_test_results = []
      unit_hw_tests = []
      if test_plan and hw_build_ids:
        for unit in test_plan.hw_test_units:
          for test in unit.hw_test_cfg.hw_test:
            unit_hw_tests.append(UnitHwTest(unit=unit, hw_test=test))
        hw_test_results = self.m.skylab_results.get_previous_results(
            hw_build_ids, unit_hw_tests)
      return vm_test_results, hw_test_results

  def set_passed_tests(self, tests: Iterable[str]):
    """Record the tests that passed in the current run.

    This exposes the tests to history, so future runs may know which tests have
    passed and which have not.

    Args:
      tests: Unique names of the tests that passed.
    """
    self.m.easy.set_properties_step(
        **{PASSED_TESTS_KEY: sorted(list(set(tests)))})

  def get_snapshot_builds(
      self, snapshot: bb_common_pb2.GitilesCommit,
      builder_list: Optional[Set[str]] = None,
      statuses: Optional[List['bb_common_pb2.Status']] = None,
      patches: Optional[List[chromiumos_common_pb2.GerritChange]] = None
  ) -> List[build_pb2.Build]:
    """Get builds ran at given snapshot and additional optional filtering.

    Args:
      snapshot: Snapshot to search on.
      builder_list: List of builder names to filter by. If falsy, no name
        filtering is performed.
      statuses: The statuses of snapshots to return. If falsy, no status
        filtering is performed.
      patches: Patches applied to snapshot to search on. If falsy, no patch
        filtering is performed.

    Returns:
      Builds with the same snapshot and additional filtering.
    """
    with self.m.step.nest('get snapshot builds') as presentation:
      project = self.m.buildbucket.build.builder.project
      builder_shell = builder_common_pb2.BuilderID(project=project,
                                                   bucket=SNAPSHOT_BUCKET)

      snapshot_builds = \
          self._get_patch_history(patches=patches,
                                  snapshot=snapshot,
                                  builder=builder_shell,
                                  statuses=statuses)

      if builder_list:
        snapshot_builds = [
            build for build in snapshot_builds
            if build.builder.builder in builder_list
        ]
      presentation.step_text = 'found %d snapshot builds' % len(snapshot_builds)
      for build in snapshot_builds:
        title = self.m.naming.get_build_title(build)
        url = self.m.buildbucket.build_url(build_id=build.id)
        presentation.links[title] = url
      return snapshot_builds

  def get_matching_builds(
      self, build: build_pb2.Build,
      statuses: Optional[List['bb_common_pb2.Status']] = None,
      start_build_id: Optional[int] = None, limit: Optional[int] = None):
    """Get builds with the matching builder and gerrit_changes.

    Args:
      build: Build to match for.
      statuses: Query for builds with these statuses.
      start_build_id: Exclude builds older than this ID.
      limit: Number of results to return. Latest first.

    Returns:
      List of builds which meet the conditions ordered from latest to oldest.
    """
    # TODO(crbug/1040552): compare builder_config.build attributes as part of
    # declaring a match.
    with self.m.step.nest('find matching builds') as presentation:
      # This intentionally uses build.input.gerrit_changes, rather than
      # self.m.cq.ordered_gerrit_changes, because the buildbucket search
      # relies on that ordering of changes.
      builds = self._get_patch_history(patches=build.input.gerrit_changes,
                                       builder=build.builder, statuses=statuses,
                                       start_build_id=start_build_id,
                                       limit=limit)
      presentation.logs['matching builds'] = [
          'https://ci.chromium.org/b/%s' % str(b.id) for b in builds
      ]
      return builds

  @functools.cached_property
  def is_retry(self) -> bool:
    """Determine if this build is being retried.

    Returns:
      Boolean indicating if it is a retry.
    """
    if self._test_data.enabled:
      is_retry = self._test_data.get('is_retry', None)
      if is_retry is not None:
        return is_retry

    builds = self.get_matching_builds(self.m.buildbucket.build,
                                      statuses=TERMINAL_STATUSES)
    return len(builds) >= 1

  @staticmethod
  def _buildset_tag_from_snapshot(snapshot: bb_common_pb2.GitilesCommit) -> str:
    """Map a snapshota commit into a buildset tag string value."""
    return '/'.join(
        ['commit/gitiles', snapshot.host, snapshot.project, '+', snapshot.id])

  def _get_patch_history(
      self, patches: Optional[List[chromiumos_common_pb2.GerritChange]] = None,
      snapshot: Optional[bb_common_pb2.GitilesCommit] = None,
      builder: Optional[builder_common_pb2.BuilderID] = None, limit: int = 2000,
      statuses: Optional[List['bb_common_pb2.Status']] = None,
      start_build_id: Optional[builder_common_pb2.BuilderID] = None,
      tags: Optional[List[bb_common_pb2.StringPair]] = None
  ) -> List[build_pb2.Build]:
    """Get all the builds with specified parameters from Buildbucket.

    Args:
      patches: Patches to search on.
      snapshot: Snapshot to search on. This will set a buildset tag and search
        on it.
      builder: Query for only this builder.
      limit: Limit the list returned to this number.
      statuses: Query for builds with these statuses.
      start_build_id: Exclude builds older than this ID.
      tags: Get builds with these tags only. If 'snapshot' is specified, then
        it will insert the 'buildset' tag for SHA1.

    Returns:
      List of builds which meet the conditions ordered from latest to oldest.
      The current build is never included in the list.
    """
    tags = [] if not tags else tags

    # Crbug/1122589: Always exclude builds created after us, to avoid deadlock.
    # Empirically, if we use end_build_id=our_build_id, it includes us in the
    # results, while end_time=my_create_time excludes us from the results.
    # See also crbug.com/996706.
    if start_build_id:
      build_range = builds_service_pb2.BuildRange(start_build_id=start_build_id)
      create_time = bb_common_pb2.TimeRange(
          end_time=self.m.buildbucket.build.create_time)
    else:
      build_range = None
      create_time = bb_common_pb2.TimeRange(
          start_time=timestamp_pb2.Timestamp(
              seconds=int(self.start_time_in_seconds)),
          end_time=self.m.buildbucket.build.create_time)

    if snapshot is not None:
      # TODO(crbug/990539): We can't use the snapshot directly because
      # BuildPredicate.output_gitiles_commit is not currently implemented by
      # buildbucket.search.
      tags.extend(
          self.m.cros_tags.tags(
              buildset=self._buildset_tag_from_snapshot(snapshot)))

    predicates = [
        builds_service_pb2.BuildPredicate(builder=builder,
                                          gerrit_changes=patches, tags=tags,
                                          create_time=create_time,
                                          build=build_range)
    ]

    # See https://crbug.com/1051623#c13.  If we have a
    # cq_equivalent_cl_group_key, then LUCI says the builds are effectively for
    # the same changes, and we can use them.
    # Per the docstring of buildbucket.search, the predicate argument is either
    # "a BuildPredicate object, or a list thereof.  If it is a list, the
    # predicates are connected with logical OR."
    if self._use_group_key:
      group_key = self.m.cros_tags.cq_equivalent_cl_group_key
      if group_key:
        predicates.append(
            builds_service_pb2.BuildPredicate(
                builder=builder, tags=self.m.cros_tags.tags(
                    cq_equivalent_cl_group_key=group_key),
                create_time=create_time, build=build_range))

    builds = self.m.buildbucket.search(
        predicates, limit=limit, url_title_fn=self.m.naming.get_build_title)

    # Filter out builds that were run on a superset of the input patches.
    # e.g. if we're trying to get the history for runs on [cl1#1], we aren't
    # interested in historical runs on [cl1#1, cl2#1].
    if patches:
      builds = [
          b for b in builds if len(patches) == len(b.input.gerrit_changes)
      ]

    if statuses:
      return [build for build in builds if build.status in statuses]
    return builds
