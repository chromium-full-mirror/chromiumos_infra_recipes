# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

# Cost is in USD per day as calculated in go/cros-infra-sizing on 2018-12-12.
# With an estimate for medium, since postdates that doc.
BOT_COST = {'small': 0.342, 'medium': 1.93, 'large': 8.08}

# Real builds always have the bot_dimension "bot_size".  The test api does
# not generally provide that, so we have a default for a better testing
# experience.
UNKNOWN_BOT_SIZE = 'UNKNOWN'


class BotCostApi(recipe_api.RecipeApi):
  """A module to calculate the cost of running bots."""

  def initialize(self):
    self._bot_size = UNKNOWN_BOT_SIZE
    for dimension in self.m.buildbucket.build.infra.swarming.bot_dimensions:
      if dimension.key == 'bot_size':
        self._bot_size = dimension.value
        break

  def set_build_cost(self, build_id, bot_size):
    """Wrapper function to calculate and set the cost of creating the build.

    Calculate the cost of creating the build and set it as a build output
    property.

    Args:
      build_id (int): The build id for this build.
      bot_size (str): The size of the bot used to create the build.
    """
    # TODO(crbug.com/1081746): drop bot_size argument and use self._bot_size.
    with self.m.step.nest('set build cost') as presentation:
      build_cost = self._calculate_build_cost(build_id, bot_size)
      presentation.properties['build_cost'] = round(build_cost, 4)

  def _calculate_build_cost(self, build_id, bot_size):
    """Calculate the cost of creating a build.

    Calculates the cost of creating a build based on the time duration. If
    the build status is terminal, the duration is based on the start_time and
    end_time, if the build status is 'STARTED', build durations is based on
    start_time and update_time.

    Args:
      build_id (int): The build id for this build.
      bot_size (str): The size of the bot used to create the build, or None to
          query swarming dimensions.

    Returns:
      A float representing the cost (USD) of building this image.
    """
    if self.m.led.run_id:  # pragma: nocover
      # If a led job, use a random id.
      build_id = 8882749049375545216

    if self._bot_size not in (bot_size, UNKNOWN_BOT_SIZE):
      with self.m.step.nest('unexpected bot_size') as presentation:
        # For now, run this as an experiment while we confirm that we are
        # getting the bot_size from the swarming dimensions correctly.
        presentation.properties['discovered_bot_size'] = self._bot_size
        presentation.step_text = 'expected bot_size "%s" got "%s"' % (
            self._bot_size, bot_size)

    build = self.m.buildbucket.get(
        build_id, step_name='calculate build cost.buildbucket.get')
    if build.status > common_pb2.ENDED_MASK:
      build_duration = build.end_time.seconds - build.start_time.seconds
    elif build.status == common_pb2.STARTED:
      build_duration = build.update_time.seconds - build.start_time.seconds
    else:
      return 0
    bot_days = build_duration / (60.0 * 60.0 * 24.0)
    return bot_days * BOT_COST[bot_size]

  def set_cq_run_cost(self, orch_build_id, child_builds):
    """Wrapper function to calculate and set the cost of the cq run.

    Calculate the cost of the cq run and set it as a build output property.

    Args:
      orch_build_id (int): The orchestrator's build id.
      child_builds (list[build_pb2.Build]): The child builds for this cq run.
    """
    with self.m.step.nest('set cq run cost') as presentation:
      cq_run_cost = self._calculate_cq_run_cost(orch_build_id, child_builds,
                                                presentation)
      presentation.properties['cq_run_cost'] = round(cq_run_cost, 4)
      orch_build_cost = self._calculate_build_cost(orch_build_id, 'small')

  def _get_child_builds_cost(self, orch_build_id, child_builds, parent_step):
    """Get the cost of building child images during this cq run.

    Get the cost for building child images during this cq run. Adds together the
    build_cost of child builds created during this cq run. Logs the build ids of
    the child builds created for this cq run that do not have a build_cost
    property.

    Args:
      orch_build_id (int): The orchestrator's build id.
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

    for build in child_builds:
      for tag in build.tags:
        if tag.key == 'parent_buildbucket_id' and int(
            tag.value) == orch_build_id:
          if 'build_cost' in build.output.properties:
            total_child_build_cost += build.output.properties['build_cost']
          else:
            child_builds_missing_cost.append(str(build.id))

    if child_builds_missing_cost:
      parent_step.logs[
          'child builds missing build_cost'] = child_builds_missing_cost
    return total_child_build_cost

  def _calculate_cq_run_cost(self, orch_build_id, child_builds, parent_step):
    """Calculates the cost of the cq run.

    Calculates the total cost of this cq run based on the cost to run the
    orchestrator and build the child images.

    Args:
      orch_build_id (int): The orchestrator's build id.
      child_builds (list[build_pb2.Build]): The child builds for this cq run.
      parent_step (Step): The calling step, to be used for presentation
      purposes.

    Returns:
      A float representing the cost (USD) of the cq run.
    """
    orch_cost = self._calculate_build_cost(orch_build_id, 'small')
    child_builds_cost = self._get_child_builds_cost(orch_build_id, child_builds,
                                                    parent_step)
    return orch_cost + child_builds_cost
