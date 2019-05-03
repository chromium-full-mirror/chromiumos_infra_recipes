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
      passed_builders = set()
      for build in self._get_patch_history(patches):
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

  def _get_patch_history(self, patches):
    """Get all the passed builds with current patch-set from Buildbucket.

    Args:
      * patches list([GerritChange]): patches to search for.

    Returns:
      A boolean to indicate whether the config has passed before
      with the patch-set.
    """
    create_time = common_pb2.TimeRange(
        start_time=timestamp_pb2.Timestamp(
            seconds=int(self.start_time_in_seconds)))
    build_predicate = rpc_pb2.BuildPredicate(status=common_pb2.SUCCESS,
                                             gerrit_changes=patches,
                                             create_time=create_time)
    return self.m.buildbucket.search(build_predicate)
