# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

# Cost is in USD per day as calculated in go/cros-infra-sizing on 2018-12-12.
BOT_COST = {'small': 4.56, 'large': 8.08}


class BotCostApi(recipe_api.RecipeApi):
  """A module to calculate the cost of running bots."""

  def calculate_build_cost(self, build_id, bot_size):
    """Calculate the cost of creating a build.

    Calculates the cost of creating a build based on the time duration. If
    the build status is terminal, the duration is based on the start_time and
    end_time, if the build status is 'STARTED', build durations is based on
    start_time and update_time.

    Args:
      build_id (int): The build id for this build.
      bot_size (str): The size of the bot used to create the build.

    Returns:
      A float representing the cost (USD) of building this image.
    """
    if self.m.led.run_id:  # pragma: nocover
      # If a led job, use a random id.
      build_id = 8882749049375545216

    build = self.m.buildbucket.get(build_id)
    if build.status > common_pb2.ENDED_MASK:
      build_duration = build.end_time.seconds - build.start_time.seconds
    elif build.status == common_pb2.STARTED:
      build_duration = build.update_time.seconds - build.start_time.seconds
    else:
      return 0
    bot_days = build_duration / (60.0 * 60.0 * 24.0)
    return bot_days * BOT_COST[bot_size]

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
          for key, value in build.output.properties.fields.items():
            if key == 'build_cost':
              total_child_build_cost += value.number_value
            break
          else:
            child_builds_missing_cost.append(str(build.id))

    if child_builds_missing_cost:
      parent_step.logs[
          'child builds missing build_cost'] = child_builds_missing_cost
    return total_child_build_cost

  def calculate_cq_run_cost(self, orch_build_id, child_builds, parent_step):
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
    orch_cost = self.calculate_build_cost(orch_build_id, 'small')
    child_builds_cost = self._get_child_builds_cost(orch_build_id, child_builds,
                                                    parent_step)
    cq_run_cost = orch_cost + child_builds_cost
    parent_step.properties['cq_run_cost'] = round(cq_run_cost, 4)
