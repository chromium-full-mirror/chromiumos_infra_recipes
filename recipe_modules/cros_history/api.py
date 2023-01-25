# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Tuple, List
import base64
import datetime
import zlib
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.chromite.api.packages import UprevPackagesResponse

from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.skylab import structs as skylab_structs
from RECIPE_MODULES.chromeos.util.util import exponential_retry

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

PASSED_TESTS_KEY = 'passed_tests'
UPREV_RESPONSE_KEY = 'compressed_uprev_response'
SNAPSHOT_BUCKET = 'postsubmit'
TEST_SUMMARY_KEY = 'test_summary'
TEST_TASKS_KEY = 'test_tasks'
TERMINAL_STATUSES = [
    common_pb2.SUCCESS,
    common_pb2.FAILURE,
    common_pb2.INFRA_FAILURE,
    common_pb2.CANCELED,
]


class CrosHistoryApi(recipe_api.RecipeApi):
  """A module to use build history to avoid redundant builds."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._use_group_key = not properties.disable_group_key
    self._lookback_seconds = properties.lookback_seconds or 5 * 24 * 60 * 60

  @property
  def start_time_in_seconds(self):
    """Generate start time in seconds."""
    return self.m.time.time() - self._lookback_seconds

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=30))
  def get_annealing_from_snapshot(self, snapshot_id):
    """Find the annealing build that created snapshot with given ID.

    Args:
      snapshot_id (str): Manifest snapshot commit ID.

    Returns:
      build_pb2.Build of the annealing build or None.
    """
    tags = self.m.cros_tags.tags(**dict(published_snapshot_id=snapshot_id))
    # Not searching based on builder because we want to find both Annealing
    # staging-Annealing builds. Tags are indexed by Buildbucket so this
    # should be fast.
    predicate = builds_service_pb2.BuildPredicate(tags=tags)
    predicate.builder.project = 'chromeos'
    return self.m.buildbucket.search(predicate, limit=1,
                                     url_title_fn=self.m.naming.get_build_title)

  def get_upreved_pkgs(self, annealing_build):
    """Retrieve the packages upreved by the annealing build.

    Args:
      annealing_build (build_pb2.Build): Annealing Build.

    Returns:
      list(PackageCPV) of upreved packages.
    """
    build_output = json_format.MessageToDict(annealing_build.output.properties)
    compressed_response = build_output.get(UPREV_RESPONSE_KEY, '')
    response_str = zlib.decompress(base64.b64decode(compressed_response))
    uprev_response = UprevPackagesResponse.FromString(response_str)
    return uprev_response.packages

  def get_passed_builds(self, tags=None):
    """Retrieve passed builds with the same patches as current build.

    Args:
      tags (list[common_pb2.StringPair]): Get builds with these tags.

    Returns:
      list([build_pb2.Build]): Passed builds with the most recent build per builder.
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
      all_passed_builds = self._get_patch_history(patches,
                                                  builder=builder_shell,
                                                  statuses=[common_pb2.SUCCESS],
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

  def get_test_failure_builders(self):
    """Get builders with the given patches that failed tests in the last run.

    Returns:
      set[str]: Names of builders with HW or VM testing failures, if any.
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

  def get_passed_tests(self):
    """Find all tests that have passed with the given patches.

    Returns:
      set[str]: Names of passed tests, if any.
    """
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

      return all_passed_tests

  def get_failed_now_exonerable_hw_tests_results(
      self, test_plan: GenerateTestPlanResponse,
      hw_build_ids: List[str]) -> List[skylab_structs.SkylabResult]:
    """Get the results from the previous failed hardware tests that can now be exonerated.

    Args:
      test_plan: The test plan for which to retrieve results.
      hw_build_ids: The IDs of the previous builds to retrieve results for.

    Returns:
      A list of the exonerable hardware test results.
    """
    unit_hw_tests = []
    if not test_plan or not hw_build_ids:
      return []
    for unit in test_plan.hw_test_units:
      for test in unit.hw_test_cfg.hw_test:
        unit_hw_tests.append(self.m.skylab.UnitHwTest(unit=unit, hw_test=test))
    hw_results = self.m.skylab.get_previous_results(hw_build_ids, unit_hw_tests)
    exonerable_hw_results = [
        result for result in hw_results
        if self.m.exonerate.is_hw_result_exonerable(result)
    ]
    return exonerable_hw_results

  def get_failed_now_exonerable_vm_test_builds(self, build_ids: List[str]
                                              ) -> List[build_pb2.Build]:
    """Get the results from the previous failed VM test builds that can now be exonerated.

    Args:
      build_ids: The IDs of the previous builds to retrieve results for.

    Returns:
      A list of the exonerable VM test builds.
    """
    vm_tests_builds = self.m.buildbucket.get_multi(
        build_ids, step_name='get tast vm tests from previous run')
    exonerable_vm_results = [
        build for build in vm_tests_builds.values()
        if self.m.exonerate.is_vm_test_build_exonerable(build)
    ]
    return exonerable_vm_results

  def get_prev_failed_now_exonerable_test_results(
      self, test_plan: GenerateTestPlanResponse
  ) -> Tuple[List[build_pb2.Build], List[skylab_structs.SkylabResult]]:
    """Get the tests  from the previous failed runs that are now exonerable.

    Args:
      test_plan: The test plan which contains the tests for which to retrieve
      the results from previous runs.

    Returns:
      A tuple containing the list of exonerable VM test builds and the list
      of exonerable HW test results.
    """

    def _get_step_text(ex_vms, ex_hws):
      return 'found %d vm suite%s and %d hw suite%s' % (
          len(ex_vms), 's' if len(ex_vms) > 1 else '', len(ex_hws),
          's' if len(ex_hws) > 1 else '')

    def _log_results(ex_vms, ex_hws):
      vm_suites_names = sorted(
          {self.m.naming.get_vm_test_title(build) for build in ex_vms})
      hw_suites_names = sorted({
          str(skylab_res.task.test.common.display_name) for skylab_res in ex_hws
      })
      presentation.logs['exonerable tests'] = (
          'Test Suites that previously failed '
          'but now exonerable \n') + 'VM test suites:\n ' + '\n '.join(
              vm_suites_names) + '\n\nHW test suites:\n ' + '\n '.join(
                  hw_suites_names)

    with self.m.step.nest(
        'get previous failed and now exonerable suites') as presentation:
      current_build = self.m.buildbucket.build
      past_builds = self.get_matching_builds(current_build,
                                             statuses=TERMINAL_STATUSES)
      if not past_builds or not past_builds[0]:
        presentation.step_text = _get_step_text([], [])
        return [], []
      last_build = past_builds[0]
      build_output = json_format.MessageToDict(last_build.output.properties)
      if TEST_TASKS_KEY not in build_output:
        presentation.step_text = _get_step_text([], [])
        return [], []

      test_tasks = build_output.get(TEST_TASKS_KEY)
      vm_build_ids = [
          int(b) for b in test_tasks.get('tast_vm_tests_builder_ids', [])
      ]
      hw_build_ids = [int(b) for b in test_tasks.get('skylab_builder_ids', [])]
      exonerable_vms = self.get_failed_now_exonerable_vm_test_builds(
          vm_build_ids)
      exonerable_hw_res = self.get_failed_now_exonerable_hw_tests_results(
          test_plan, hw_build_ids)
      presentation.step_text = _get_step_text(exonerable_vms, exonerable_hw_res)
      _log_results(exonerable_vms, exonerable_hw_res)
      return exonerable_vms, exonerable_hw_res

  def set_passed_tests(self, tests):
    """Record the tests that passed in the current run.

    This exposes the tests to history, so future runs may know which tests
    have passed and which have not.

    Args:
      tests (sequence[str]): (Unique) names of the tests that passed.
    """
    # TODO(b:232246919): Figure out why this is failing, and re-enable.
    #if len(tests) != len(set(tests)):
    #      raise ValueError('test names must be unique, found: %r' % tests)
    self.m.easy.set_properties_step(
        **{PASSED_TESTS_KEY: sorted(list(set(tests)))})

  def get_snapshot_builds(self, snapshot, builder_list=None, statuses=None,
                          patches=None):
    """Get builds ran at given snapshot and additional optional filtering.

    Args:
      snapshot (GitilesCommit): Snapshot to search on.
      builder_list (set[str]): List of builder names to filter by. If
        falsy, no name filtering is performed.
      statuses ([common_pb2.Status]): The statuses of snapshots to return.
        If falsy, no status filtering is performed.
      patches ([GerritChange]): Patches applied to snapshot to search on.
        If falsy, no patch filtering is performed.

    Returns:
      list[Build] builds with the same snapshot and additional filtering.
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

  def get_matching_builds(self, build, statuses=None, start_build_id=None,
                          limit=None):
    """Get builds with the matching builder and gerrit_changes.

    Args:
      build (build_pb2.Build): build to match for.
      statuses ([common_pb2.Status]): query for builds with these statuses.
      start_build_id (int): exclude builds older than this ID.
      limit (int): number of results to return. Latest first.

    Returns:
      list[Build] which meet the conditions ordered from latest to oldest.
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

  def is_retry(self):
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
  def _buildset_tag_from_snapshot(snapshot):
    """Map a snapshot (GitilesCommit) into a buildset tag string value."""
    return "/".join(
        ['commit/gitiles', snapshot.host, snapshot.project, '+', snapshot.id])

  def _get_patch_history(self, patches=None, snapshot=None, builder=None,
                         limit=2000, statuses=None, start_build_id=None,
                         tags=None):
    """Get all the builds with specified parameters from Buildbucket.

    Args:
      patches list([GerritChange]): patches to search on.
      snapshot (GitilesCommit): snapshot to search on. This
        will set a buildset tag and search on it.
      builder (BuilderID): query for only this builder.
      limit (int): limit the list returned to this number.
      statuses ([common_pb2.Status]): query for builds with these statuses.
      start_build_id: exclude builds older than this ID.
      tags ([common_pb2.StringPair]): get builds with these tags only. If
        'snapshot' is specified then it will insert 'buildset' tag for SHA1.

    Returns:
      list[Build] which meet the conditions ordered from latest to oldest.  The
        current build is never included in the list.
    """
    tags = [] if not tags else tags

    # Crbug/1122589: Always exclude builds created after us, to avoid deadlock.
    # Empirically, if we use end_build_id=our_build_id, it includes us in the
    # results, while end_time=my_create_time excludes us from the results.
    # See also crbug.com/996706.
    if start_build_id:
      build_range = builds_service_pb2.BuildRange(start_build_id=start_build_id)
      create_time = common_pb2.TimeRange(
          end_time=self.m.buildbucket.build.create_time)
    else:
      build_range = None
      create_time = common_pb2.TimeRange(
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
