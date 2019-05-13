# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2

from recipe_engine import recipe_api
from google.protobuf import timestamp_pb2


class HistoryAwareApi(recipe_api.RecipeApi):
  """A module to use build history to avoid redundant builds."""

  def __init__(self, lookback_no_of_seconds, *args, **kwargs):
    super(HistoryAwareApi, self).__init__(*args, **kwargs)
    self._lookback_no_of_seconds = lookback_no_of_seconds

  @property
  def start_time_in_seconds(self):
    """Generate start time in seconds."""
    return self.m.time.time() - self._lookback_no_of_seconds

  def get_build_target(self, build):
    """Retrieve the build target for input build.

    Args:
      * build: input Build instance.

    Returns:
      A string with build_target of the input Build object. If not found,
      return None.
    """
    if 'build_target' in build.input.properties:
      if 'name' in build.input.properties['build_target']:
        return build.input.properties['build_target']['name']

    return None

  def passed_builds(self, patches):
    """Retrieve passed builds with the same patches.

    Args:
      * patches (list[GerritChange]): patches in the current build.

    Returns:
      A list([build_pb2.Build]) with at most one build per builder.
    """
    with self.m.step.nest('Looking for successful builds'):
      if not patches:
        return []

      previously_passed_builds = []
      # Start with cq-orchestrator so we don't add it to the result.
      passed_builders = set([self.m.buildbucket.build.builder.builder])
      for build in self._get_patch_history(patches, success_only=True):
        if build.builder.builder not in passed_builders:
          passed_builders.add(build.builder.builder)
          previously_passed_builds.append(build)

      self._log_previous_builds(previously_passed_builds)
      return previously_passed_builds

  def _log_previous_builds(self, builds_list):
    """Write a link to the previously passed builds.

    Args:
      * builds_list list([build_pb2.Build]): builds to print.
    """
    if builds_list:
      step = self.m.step('filter build requests', [])
      step.presentation.step_text = 'Some builds have passed before:'
      for build in builds_list:
        build_url = self.m.buildbucket.build_url(build_id=build.id)
        step.presentation.links[build.builder.builder] = build_url

  def _log_previous_tests(self, build_target_map):
    """Write a link to the previous passed tests.

    Args:
      * build_target_map dict(str->int): A mapping from build_target to
          ID of the orchestrator build to link to.
    """
    if build_target_map:
      step = self.m.step('cros_history', [])
      step.presentation.step_text = 'Some tests have passed before:'
      for build_target, build_id in build_target_map.iteritems():
        build_url = self.m.buildbucket.build_url(build_id=build_id)
        step.presentation.links[build_target] = build_url

  def passed_targets(self, patches):
    """Retrieve tests that have passed with same patches.

    Args:
      * patches (list[GerritChange]): patches in the current build.

    Returns:
      A set of build_targets that have passed testing.
    """
    with self.m.step.nest('Looking for successful tests'):
      if not patches:
        return set()

      target_build_map = {}
      for previous_build in self._get_patch_history(
          patches, builder=self.m.buildbucket.build.builder):
        if 'build_target_test_status' in previous_build.output.properties:
          test_results = previous_build.output.properties[
              'build_target_test_status']
          if test_results:
            for build_target in test_results:
              result_str = test_results[build_target]
              if result_str == 'success':
                if build_target not in target_build_map:
                  target_build_map[build_target] = previous_build.id

      self._log_previous_tests(target_build_map)
      return set(target_build_map.keys())

  def _get_patch_history(self, patches, builder=None, success_only=False):
    """Get all the passed builds with current patch-set from Buildbucket.

    Args:
      * patches list([GerritChange]): patches to search for.
      * builder (BuilderID): query for only this builder.
      * success_only (bool): query only successful builds.

    Returns:
      A boolean to indicate whether the config has passed before
      with the patch-set.
    """
    create_time = common_pb2.TimeRange(
        start_time=timestamp_pb2.Timestamp(
            seconds=int(self.start_time_in_seconds)))
    status = common_pb2.SUCCESS if success_only else None
    build_predicate = rpc_pb2.BuildPredicate(
        status=status, builder=builder, gerrit_changes=patches,
        create_time=create_time)
    return self.m.buildbucket.search(build_predicate,
                                     url_title_fn=self.m.naming.get_build_title)
