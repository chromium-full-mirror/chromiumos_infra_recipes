# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2

from recipe_engine import recipe_api

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

PASSED_TESTS_KEY = 'passed_tests'
SNAPSHOT_BUCKET = 'postsubmit'


class CrosHistoryApi(recipe_api.RecipeApi):
  """A module to use build history to avoid redundant builds."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosHistoryApi, self).__init__(*args, **kwargs)
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
      list([build_pb2.Build]): Passed builds with at most one build per builder.
    """
    with self.m.step.nest('get change build history') as step:
      passed_builds = []
      # Start with cq-orchestrator so we don't add it to the result.
      current_builder_id = self.m.buildbucket.build.builder
      passed_builders = set([current_builder_id.builder])
      patches = self.m.buildbucket.build.input.gerrit_changes
      # We don't want to specify the builder, but, we should specify the bucket
      builder_shell = build_pb2.BuilderID(project=current_builder_id.project,
                                          bucket=current_builder_id.bucket)
      for build in self._get_patch_history(patches, builder=builder_shell,
                                           statuses=[common_pb2.SUCCESS],
                                           tags=tags):
        if build.builder.builder not in passed_builders:
          passed_builders.add(build.builder.builder)
          passed_builds.append(build)

      step.presentation.step_text = ('some builds already completed'
                                     if passed_builds else
                                     'found no completed builds')
      passed_builds.sort(key=lambda build: build.builder.builder)
      for build in passed_builds:
        title = self.m.naming.get_build_title(build)
        url = self.m.buildbucket.build_url(build_id=build.id)
        step.presentation.links[title] = url

      return passed_builds

  def get_passed_tests(self):
    """Find all tests that have passed with the given patches.

    Returns:
      set[str]: Names of passed tests, if any.
    """
    with self.m.step.nest('get change test history') as step:
      current_build = self.m.buildbucket.build
      past_builds = self.get_matching_builds(current_build)

      all_passed_tests = set()
      for build in past_builds:
        build_output = json_format.MessageToDict(build.output.properties)
        passed_tests = build_output.get(PASSED_TESTS_KEY, [])
        all_passed_tests |= set(passed_tests)

      step.presentation.step_text = ('some tests already passed'
                                     if all_passed_tests else
                                     'found no previously passed tests')
      if all_passed_tests:
        step.presentation.logs['list of passed tests'] = sorted(
            all_passed_tests)

      return all_passed_tests

  def set_passed_tests(self, tests):
    """Record the tests that passed in the current run.

    This exposes the tests to history, so future runs may know which tests
    have passed and which have not.

    Args:
      tests (sequence[str]): (Unique) names of the tests that passed.
    """
    if len(tests) != len(set(tests)):
      raise ValueError('test names must be unique, found: %r' % tests)
    self.m.easy.set_property_step(PASSED_TESTS_KEY, tests)

  def get_snapshot_builds(self, snapshot, builder_list, statuses):
    """Get *-snapshot builds with the given snapshot.

    Args:
      snapshot (GitilesCommit): Snapshot to search on.
      builder_list (set[str]): List of builder names to filter by.
      statuses ([common_pb2.Status]): The statuses of snapshots to return

    Returns:
      list[Build] *-snapshot builds with the same snapshot filtered
      by the builder_list.
    """
    with self.m.step.nest('get snapshot builds') as step:
      project = self.m.buildbucket.build.builder.project
      builder_shell = build_pb2.BuilderID(project=project,
                                          bucket=SNAPSHOT_BUCKET)
      # We cannot use snapshot directly because the set of fields
      # ('host', 'id', 'project', 'ref') is unsupported by buildbucket.
      # Limiting to ('host', 'id', 'project').
      search_snapshot = common_pb2.GitilesCommit(
          host=snapshot.host, project=snapshot.project, id=snapshot.id)

      all_snapshot_builds = \
          self._get_patch_history(snapshot=search_snapshot,
                                  builder=builder_shell,
                                  statuses=statuses)

      snapshot_builds = [
          build for build in all_snapshot_builds
          if build.builder.builder in builder_list
      ]
      step.presentation.step_text = 'found %d snapshot builds' % len(
          snapshot_builds)
      for build in snapshot_builds:
        title = self.m.naming.get_build_title(build)
        url = self.m.buildbucket.build_url(build_id=build.id)
        step.presentation.links[title] = url
      return snapshot_builds

  def get_matching_builds(self, build, statuses=None, start_build_id=None):
    """Get builds with the matching builder and gerrit_changes.

    Args:
      build (build_pb2.Build): build to match for.
      statuses ([common_pb2.Status]): query for builds with these statuses.
      start_build_id (int): query builds older than this ID.

    Returns:
      list[Build] which meet the conditions ordered from latest to oldest.
    """
    with self.m.step.nest('find matching builds'):
      # This intentionally uses build.input.gerrit_changes, rather than
      # self.m.cq.ordered_gerrit_changes, because the buildbucket search
      # relies on that ordering of changes.
      return self._get_patch_history(patches=build.input.gerrit_changes,
                                     builder=build.builder, statuses=statuses,
                                     start_build_id=start_build_id)

  @staticmethod
  def _buildset_tag_from_snapshot(snapshot):
    """Map a snapshot (GitilesCommit) into a buildset tag string value."""
    return "/".join(
        ['commit/gitiles', snapshot.host, snapshot.project, '+', snapshot.id])

  def _get_patch_history(self, patches=None, snapshot=None, builder=None,
                         limit=1000, statuses=None, start_build_id=None,
                         tags=None):
    """Get all the builds with specified parameters from Buildbucket.

    Args:
      patches list([GerritChange]): patches to search on.
      snapshot (GitilesCommit): snapshot to search on. This
        will set a buildset tag and search on it.
      builder (BuilderID): query for only this builder.
      limit (int): limit the list returned to this number, default 1000.
      statuses ([common_pb2.Status]): query for builds with these statuses.
      start_build_id: query builds older than this ID.
      tags ([common_pb2.StringPair]): get builds with these tags only. If
        'snapshot' is specified then it will insert 'buildset' tag for SHA1.

    Returns:
      list[Build] which meet the conditions ordered from latest to oldest.
    """
    tags = [] if not tags else tags

    # BuildRange and TimeRange are mutually exclusive.
    if start_build_id:
      build_range = rpc_pb2.BuildRange(start_build_id=start_build_id)
      create_time = None
    else:
      build_range = None
      create_time = common_pb2.TimeRange(
          start_time=timestamp_pb2.Timestamp(
              seconds=int(self.start_time_in_seconds)))

    if snapshot is not None:
      # we can't use the snapshot directly because output_gitiles_commit
      # is not currently implemented, TODO(crbug/990539)
      buildset_tag = common_pb2.StringPair(
          key='buildset',
          value=CrosHistoryApi._buildset_tag_from_snapshot(snapshot))
      tags.append(buildset_tag)

    build_predicate = rpc_pb2.BuildPredicate(
        builder=builder, gerrit_changes=patches, tags=tags,
        create_time=create_time, build=build_range)

    builds = self.m.buildbucket.search(
        build_predicate, limit=limit,
        url_title_fn=self.m.naming.get_build_title)

    # We'd prefer to stop rather than return truncated results.
    if len(builds) == limit:
      raise RuntimeError("Number of buildbucket search results exceeds limit {}"
                         .format(limit))  # pragma: no cover

    if statuses:
      return [build for build in builds if build.status in statuses]
    else:
      return builds
