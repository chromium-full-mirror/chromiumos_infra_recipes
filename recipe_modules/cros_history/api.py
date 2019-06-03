# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2

from recipe_engine import recipe_api

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

PASSED_TESTS_KEY = 'passed_tests'


class CrosHistoryApi(recipe_api.RecipeApi):
  """A module to use build history to avoid redundant builds."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosHistoryApi, self).__init__(*args, **kwargs)
    self._lookback_seconds = properties.lookback_seconds or 5 * 24 * 60 * 60

  @property
  def start_time_in_seconds(self):
    """Generate start time in seconds."""
    return self.m.time.time() - self._lookback_seconds

  def get_passed_builds(self, patches):
    """Retrieve passed builds with the same patches.

    Args:
      patches (list[GerritChange]): patches in the current build.

    Returns:
      list([build_pb2.Build]): Passed builds with at most one build per builder.
    """
    assert patches, 'cannot get build history without gerrit changes'
    with self.m.step.nest('get change build history') as step:
      passed_builds = []
      # Start with cq-orchestrator so we don't add it to the result.
      passed_builders = set([self.m.buildbucket.build.builder.builder])
      for build in self._get_patch_history(patches, status=common_pb2.SUCCESS):
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

  def get_passed_tests(self, patches):
    """Find all tests that have passed with the given patches.

    Args:
      patches (list[GerritChange]): Gerrit patches being tested.

    Returns:
      set[str]: Names of passed tests, if any.
    """
    assert patches, 'cannot get test history without gerrit changes'
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
    with self.m.step.nest('record passed tests') as step:
      step.presentation.properties[PASSED_TESTS_KEY] = tests

  def get_matching_builds(self, build, status=None, start_build_id=None):
    """Get builds with the matching builder and gerrit_changes.

    Args:
      build (build_pb2.Build): build to match for.
      status (common_pb2.Status): query for builds with this status.
      start_build_id (int): query builds older than this ID.

    Returns:
      list[Build] which meet the conditions ordered from latest to oldest.
    """
    with self.m.step.nest('find matching builds'):
      # This intentionally uses build.input.gerrit_changes, rather than
      # self.m.cq.ordered_gerrit_changes, because the buildbucket search
      # relies on that ordering of changes.
      return self._get_patch_history(patches=build.input.gerrit_changes,
                                     builder=build.builder, status=status,
                                     start_build_id=start_build_id)

  def _get_patch_history(self, patches, builder=None, limit=None, status=None,
                         start_build_id=None):
    """Get all the passed builds with current patch-set from Buildbucket.

    Args:
      * patches list([GerritChange]): patches to search for.
      * builder (BuilderID): query for only this builder.
      * limit (int): limit the list returned to this number.
      * status (common_pb2.Status): query for builds with this status.
      * start_build_id: query builds older than this ID.

    Returns:
      list[Build] which meet the conditions ordered from latest to oldest.
    """
    # BuildRange and TimeRange are mutually exclusive.
    if start_build_id:
      build_range = rpc_pb2.BuildRange(start_build_id=start_build_id)
      create_time = None
    else:
      build_range = None
      create_time = common_pb2.TimeRange(
          start_time=timestamp_pb2.Timestamp(
              seconds=int(self.start_time_in_seconds)))
    build_predicate = rpc_pb2.BuildPredicate(
        builder=builder, status=status, gerrit_changes=patches,
        create_time=create_time, build=build_range)
    return self.m.buildbucket.search(build_predicate, limit=limit,
                                     url_title_fn=self.m.naming.get_build_title)
