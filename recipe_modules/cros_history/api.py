# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder as builder_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.testplans.generate_test_plan import TestUnitCommon
from PB.testplans.generate_test_plan import HwTestUnit

from recipe_engine import recipe_api

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

FAILED_HW_TESTS_KEY = 'hw_test_failures'
FAILED_TESTS_KEY = 'test_failures'
PASSED_TESTS_KEY = 'passed_tests'
SNAPSHOT_BUCKET = 'postsubmit'


class CrosHistoryApi(recipe_api.RecipeApi):
  """A module to use build history to avoid redundant builds."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosHistoryApi, self).__init__(*args, **kwargs)
    self._use_group_key = not properties.disable_group_key
    self._lookback_seconds = properties.lookback_seconds or 5 * 24 * 60 * 60

  @property
  def start_time_in_seconds(self):
    """Generate start time in seconds."""
    return self.m.time.time() - self._lookback_seconds

  def get_passed_builds(self, tags=None):
    """Retrieve passed builds with the same patches as current build.

    Args:
      tags (list[common_pb2.StringPair]): Get builds with these tags.

    Returns:
      list([build_pb2.Build]): Passed builds with the most recent build per builder.
    """
    with self.m.step.nest('get change build history') as presentation:
      # TODO(b/186520766): Debug information. Remove after bug is resolved.
      presentation.properties['use_group_key'] = self._use_group_key
      presentation.properties['cq_equivalent_cl_group_key'] = (
          self.m.cros_tags.cq_equivalent_cl_group_key)
      build = self.m.buildbucket.build
      latest_passed_builds = []
      # Start with cq-orchestrator so we don't add it to the result.
      current_builder_id = build.builder
      passed_builders = set([current_builder_id.builder])
      patches = build.input.gerrit_changes
      # We don't want to specify the builder, but, we should specify the bucket
      builder_shell = builder_pb2.BuilderID(project=current_builder_id.project,
                                            bucket=current_builder_id.bucket)
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
    """Get builders with the given patches that failed HW tests in the last run.

    Returns:
      set[str]: Names of builders with HW testing failures, if any.
    """
    current_build = self.m.buildbucket.build
    past_builds = self.get_matching_builds(current_build)
    if not past_builds:
      return set()
    past_builds.sort(key=lambda build: build.start_time.seconds)
    latest_completed_build = past_builds[-1]

    build_output = json_format.MessageToDict(
        latest_completed_build.output.properties)
    failed_tests = build_output.get(FAILED_TESTS_KEY, [])
    if not failed_tests:
      return set()
    failed_hw_tests = [
        json_format.Parse(test['test_spec'], HwTestUnit())
        for test in failed_tests.get(FAILED_HW_TESTS_KEY, [])
    ]

    return set([test.common.builder_name for test in failed_hw_tests])

  def get_passed_tests(self):
    """Find all tests that have passed with the given patches.

    Returns:
      set[str]: Names of passed tests, if any.
    """
    with self.m.step.nest('get change test history') as presentation:
      current_build = self.m.buildbucket.build
      past_builds = self.get_matching_builds(current_build)

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

  def set_passed_tests(self, tests):
    """Record the tests that passed in the current run.

    This exposes the tests to history, so future runs may know which tests
    have passed and which have not.

    Args:
      tests (sequence[str]): (Unique) names of the tests that passed.
    """
    # TODO(dhanyaganesh): Figure out why this is failing.
    #if len(tests) != len(set(tests)):
    #      raise ValueError('test names must be unique, found: %r' % tests)
    self.m.easy.set_properties_step(**{PASSED_TESTS_KEY: list(set(tests))})

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
      builder_shell = builder_pb2.BuilderID(project=project,
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
      start_build_id (int): query builds older than this ID.
      limit (int): number of results to return. Latest first.

    Returns:
      list[Build] which meet the conditions ordered from latest to oldest.
    """
    # TODO(crbug/1040552): compare builder_config.build attributes as part of
    # declaring a match.
    with self.m.step.nest('find matching builds'):
      # This intentionally uses build.input.gerrit_changes, rather than
      # self.m.cq.ordered_gerrit_changes, because the buildbucket search
      # relies on that ordering of changes.
      return self._get_patch_history(patches=build.input.gerrit_changes,
                                     builder=build.builder, statuses=statuses,
                                     start_build_id=start_build_id, limit=limit)

  def is_retry(self, build):
    """Determine if this build is being retried.

    Args:
      build (build_pb2.Build): The build to match for.

    Returns:
      Boolean indicating if it is a retry.
    """
    if self._test_data.enabled:
      is_retry = self._test_data.get('is_retry', None)
      if is_retry is not None:
        return is_retry

    return len(self.get_matching_builds(self.m.buildbucket.build)) > 1

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
      start_build_id: query builds older than this ID.
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
    else:
      return builds
