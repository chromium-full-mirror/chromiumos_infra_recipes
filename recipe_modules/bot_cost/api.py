# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for calculating bot cost."""

import contextlib
from typing import List

from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from recipe_engine.post_process_inputs import Step
from recipe_engine.recipe_api import RecipeApi

# Cost is in USD per hour, last updated in 02/2024.
# Calculated from https://cloud.google.com/compute/vm-instance-pricing,
# using the us-west4 zone.
# Use "Price", not "Spot Price".
BOT_COST = {
    # Will set cost to zero if we don't have a lookup.
    'unknown': 0.0,
    # TODO(b/323350989): Update or remove.
    'small': 0.01425,
    # TODO(b/323350989): Update or remove.
    'smedium': 0.001675,
    # TODO(b/323350989): Update or remove.
    'medium': 0.08042,
    # TODO(b/323350989): Update or remove.
    'large': 0.337,
    # TODO(b/323350989): Update or remove.
    'xlarge': 0.337,
    # TODO(b/323350989): Update or remove.
    'xxlarge': 0.599,
    # Calculated using 32 cores, 64gb RAM and
    # the custom e2 costs.
    'custom-32-65536': 1.21,
    'e2-custom-32-65536': 1.21,
    'f1-micro': .0086,
    'g1-small': .0289,
    'e2-medium': 0.037731,
    'e2-small': 0.018866,
    'e2-standard-2': 0.075462,
    'e2-standard-4': 0.150924,
    'e2-standard-8': 0.301848,
    'e2-standard-16': 0.603696,
    'e2-standard-32': 1.207392,
    'n1-standard-1': 0.0535,
    'n1-standard-2': 0.107,
    'n1-standard-4': 0.214,
    'n1-standard-8': 0.428,
    'n1-standard-16': 0.856,
    'n1-standard-32': 1.712,
    'n2-highcpu-64': 2.583936,
    'n2d-highcpu-64': 2.248128,
    'n2d-highmem-64': 4.107776,
    'n2d-standard-2': 0.09516,
    'n2d-standard-4': 0.19032,
    'n2d-standard-8': 0.38064,
    'n2d-standard-16': 0.76128,
    'n2d-standard-32': 1.52256,
    'n2d-standard-48': 2.28384,
    'n2d-standard-64': 3.04512,
    'n2d-standard-80': 3.8064,
    'n2d-standard-96': 4.56768,
    'n2d-standard-128': 6.09024,
    'n2d-standard-224': 10.65792,
}


class BotCostApi(RecipeApi):
  """A module to calculate the cost of running bots."""

  def initialize(self):
    self._bot_size = None
    # If we are led launched, this lets us at least estimate the actual time
    # spend in the run.
    self._start_time = self.m.time.time()

  @property
  def bot_size(self) -> str:
    if not self._bot_size:
      swarming = self.m.buildbucket.build.infra.swarming
      for dimension in swarming.bot_dimensions or swarming.task_dimensions:
        if dimension.key == 'bot_size':
          if dimension.value not in BOT_COST:
            self._bot_size = 'unknown'
          else:
            self._bot_size = dimension.value
          break
    return self._bot_size

  @contextlib.contextmanager
  def build_cost_context(self):
    """Set build cost after running.

    Returns:
      A context that sets build_cost on exit.
    """
    try:
      yield
    finally:
      self.set_build_run_cost()

  def set_build_run_cost(self):
    """Wrapper function to calculate and set the cost of the run.

    Calculate the cost of the run and set it as a build output property.
    Includes cost of any child builds.
    """
    with self.m.step.nest('set build cost') as presentation:
      child_builds = self._get_child_builds()
      build_cost = self._calulate_build_cost(child_builds, presentation)
      presentation.properties['build_cost'] = round(build_cost, 4)

  def _calculate_current_build_cost(self) -> float:
    """Calculate the cost of running the current build.

    Calculates the cost of creating a build based on the time duration. If
    the build status is terminal, the duration is based on the start_time and
    end_time, if the build status is 'STARTED', build durations is based on
    start_time and update_time.

    Returns:
      A float representing the cost (USD) of building this image.
    """
    # If we didn't get a bot_size, give it a zero cost.
    # TODO(lamontjones): consider fetching bot_policy.cfg and using the
    # hourlyCost field.
    daily_cost = BOT_COST.get(self.bot_size, 0.0) * 24

    build = self.m.buildbucket.build
    if self.m.led.run_id or build.status == common_pb2.STATUS_UNSPECIFIED:
      # If this led job, use a known-ended build, since the led job doesn't
      # track start/end times.
      build.start_time.seconds = int(self._start_time)
      build.update_time.seconds = int(self.m.time.time())
      build.status = common_pb2.STARTED
    else:
      # Refresh the build information.
      build = self.m.buildbucket.get(
          build.id, step_name='calculate build cost.buildbucket.get')

    if build.status & common_pb2.ENDED_MASK:
      # Cases that take this path:
      # 1. led jobs (The build id used above is status=SUCCESS.)
      # 2. Testing.
      build_duration = build.end_time.seconds - build.start_time.seconds
    elif build.status == common_pb2.STARTED:
      # Since we are calculating our cost while we are still running, any build
      # scheduled via buildbucket will be status=STARTED.
      build_duration = build.update_time.seconds - build.start_time.seconds
    else:
      # The only remaining options are SCHEDULED and STATUS_UNSPECIFIED. (How
      # are we even running?)  These situations occur only in tests, and we
      # return a zero cost.
      return 0.0
    bot_days = build_duration / (60.0 * 60.0 * 24.0)
    return bot_days * daily_cost

  def _get_child_builds(self) -> List[Build]:
    """Get the child builders for this orchestrator."""
    # We only really care about id and output.properties.bot_cost, but
    # buildbucket wants to give builder and status as well, so ask for them.
    fields = frozenset({'id', 'builder', 'status', 'output'})
    predicate = builds_service_pb2.BuildPredicate(
        tags=self.m.buildbucket.tags(
            parent_buildbucket_id=str(self.m.buildbucket.build.id)))
    predicate.builder.project = self.m.buildbucket.build.builder.project
    return self.m.buildbucket.search(predicate, fields=fields)

  @staticmethod
  def _get_child_builds_cost(child_builds: List[Build],
                             parent_step: Step) -> float:
    """Get the cost of running child builders.

    Adds together the build_cost of child builds created during the build.
    Logs the build ids of the child builds created for this build that do not
    have a build_cost property.

    Args:
      child_builds: The builds completed for this run.
      parent_step: The calling step, to be used for presentation purposes.

    Returns:
      total_child_build_cost: The cost (USD) of building child images during
      this run.
    """
    total_child_build_cost = 0
    child_builds_missing_cost = []

    for build in child_builds:
      if 'build_cost' in build.output.properties:
        total_child_build_cost += build.output.properties['build_cost']
      else:
        child_builds_missing_cost.append(str(build.id))

    if child_builds_missing_cost:
      parent_step.logs[
          'child builds missing build_cost'] = child_builds_missing_cost
    return total_child_build_cost

  def _calulate_build_cost(self, child_builds: List[Build],
                           parent_step: Step) -> float:
    """Calculates the cost of the run, including the children.

    Calculates the total cost of this run based on the cost to run the build
    and all children.

    Args:
      child_builds: The child builds for this run.
      parent_step: The calling step, to be used for presentation purposes.

    Returns:
      A float representing the cost (USD) of the run.
    """
    cost = self._calculate_current_build_cost()

    build = self.m.buildbucket.build
    if not (self.m.led.run_id or build.status == common_pb2.STATUS_UNSPECIFIED):
      cost += self._get_child_builds_cost(child_builds, parent_step)
    return cost
