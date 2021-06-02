# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib

from recipe_engine.recipe_api import RecipeApi, StepFailure

from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

# Cost values are hourly pulled from bot_policies_helper.
# Cost is in USD per day, last updated on 05/05/2020.
MACHINE_HOURLY_COST = {
    'custom-32-65536': 0.337,
    'e2-custom-32-65536': 0.279,
    'f1-micro': .00228,
    'g1-small': .00771,
    'e2-medium': 0.0101,
    'e2-small': 0.0050,
    'e2-standard-4': 0.0402,
    'e2-standard-8': 0.0804,
    'e2-standard-16': 0.1608,
    'e2-standard-32': 0.3217,
    'n1-standard-1': 0.0143,
    'n1-standard-2': 0.0285,
    'n1-standard-4': 0.057,
    'n1-standard-8': 0.114,
    'n1-standard-16': 0.228,
    'n1-standard-32': 0.456,
    'n2d-highcpu-64': 0.599,
}


class BotCostApi(RecipeApi):
  """A module to calculate the cost of running bots."""

  def initialize(self):
    self._machine_type = None
    # If we are led launched, this lets us at least estimate the actual time
    # spend in the run.
    self._start_time = self.m.time.time()
    self._build_run_cost = 0
    self._cq_run_cost = 0

  @property
  def machine_type(self):
    if not self._machine_type:
      swarming = self.m.buildbucket.build.infra.swarming
      for dimension in swarming.bot_dimensions or swarming.task_dimensions:
        if dimension.key == 'machine_type':
          if dimension.value not in MACHINE_HOURLY_COST:
            raise StepFailure('machine_type:{} not supported'.format(
                dimension.value))
          self._machine_type = dimension.value
          break
    return self._machine_type

  @contextlib.contextmanager
  def build_cost_context(self):
    """Set build cost after running.

    Returns:
      A context that sets build_cost on exit.
    """
    try:
      yield
    finally:
      self.set_build_cost()

  @contextlib.contextmanager
  def cq_run_cost_context(self):
    """Set cq cost after running.

    Returns:
      A context that sets cq_run_cost on exit.
    """
    try:
      yield
    finally:
      self.set_cq_run_cost()

  def set_build_cost(self):
    """Wrapper function to calculate and set the cost of creating the build.

    Calculate the cost of creating the build and set it as a build output
    property.
    """
    with self.m.step.nest('set build cost') as presentation:
      presentation.logs['machine_type'] = [str(self.machine_type)]
      build_cost = self._calculate_build_cost()
      presentation.properties['build_cost'] = round(build_cost, 4)
      self._build_run_cost = build_cost

  def _calculate_build_cost(self):
    """Calculate the cost of creating a build.

    Calculates the cost of creating a build based on the time duration. If
    the build status is terminal, the duration is based on the start_time and
    end_time, if the build status is 'STARTED', build durations is based on
    start_time and update_time.

    Args:
      build_id (int): The build id for this build.

    Returns:
      A float representing the cost (USD) of building this image.
    """
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

    # If we didn't get a machine_type, give it a zero cost.
    # Cost is hourly, therefore we calcuate for a total daily cost.
    # TODO(lamontjones): consider fetching bot_policy.cfg and using the
    # hourlyCost field.
    hourly_cost = MACHINE_HOURLY_COST.get(self.machine_type, 0.0)

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
    return bot_days * (hourly_cost * 24)

  def set_cq_run_cost(self, child_builds=None):
    """Wrapper function to calculate and set the cost of the cq run.

    Calculate the cost of the cq run and set it as a build output property.

    Args:
      child_builds (list[build_pb2.Build]): The child builds for this cq run.
    """
    with self.m.step.nest('set cq run cost') as presentation:
      child_builds = child_builds or self._get_child_builds()
      cq_run_cost = self._calculate_cq_run_cost(child_builds, presentation)
      presentation.properties['cq_run_cost'] = round(cq_run_cost, 4)
      self._cq_run_cost = cq_run_cost

  def _get_child_builds(self):
    """Get the child builders for this orchestrator."""
    # We only really care about id and output.properties.bot_cost, but
    # buildbucket wants to give builder and status as well, so ask for them.
    fields = frozenset({'id', 'builder', 'status', 'output'})
    predicate = builds_service_pb2.BuildPredicate(
        tags=self.m.buildbucket.tags(
            parent_buildbucket_id=str(self.m.buildbucket.build.id)))
    predicate.builder.project = self.m.buildbucket.build.builder.project
    return self.m.buildbucket.search(predicate, fields=fields)

  def _get_child_builds_cost(self, child_builds, parent_step):
    """Get the cost of building child images during this cq run.

    Get the cost for building child images during this cq run. Adds together the
    build_cost of child builds created during this cq run. Logs the build ids of
    the child builds created for this cq run that do not have a build_cost
    property.

    Args:
      child_builds (list[build_pb2.Build]): The builds completed for this cq
      run.
      parent_step (Step): The calling step, to be used for presentation
      purposes.

    Returns:
      total_child_build_cost (float): The cost (USD) of building child images
      during this cq run.
    """
    total_child_build_cost = 0
    child_builds_missing_cost = []

    orch_build_id = self.m.buildbucket.build.id
    for build in child_builds:
      if 'build_cost' in build.output.properties:
        total_child_build_cost += build.output.properties['build_cost']
      else:
        child_builds_missing_cost.append(str(build.id))

    if child_builds_missing_cost:
      parent_step.logs[
          'child builds missing build_cost'] = child_builds_missing_cost
    return total_child_build_cost

  def _calculate_cq_run_cost(self, child_builds, parent_step):
    """Calculates the cost of the cq run.

    Calculates the total cost of this cq run based on the cost to run the
    orchestrator and build the child images.

    Args:
      child_builds (list[build_pb2.Build]): The child builds for this cq run.
      parent_step (Step): The calling step, to be used for presentation
      purposes.

    Returns:
      A float representing the cost (USD) of the cq run.
    """
    orch_cost = self._calculate_build_cost()
    child_builds_cost = self._get_child_builds_cost(child_builds, parent_step)
    return orch_cost + child_builds_cost
