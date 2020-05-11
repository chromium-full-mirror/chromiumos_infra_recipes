# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class SwarmingCliTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the swarming CLI module."""

  def swarming_bot_step_test_data(self, dimensions):
    """Returns list of bots based on provided dimensions.

    Args:
      dimensions(dict): Dictionary of dimensions
    """
    bot_counts = {}
    for dim in dimensions:
      if 'cq' in dim:
        bot_counts = {
            "busy": "21",
            "count": "23",
            "dead": "0",
            "maintenance": "0",
            "now": "2020-03-26T23:38:02.383828",
            "quarantined": "0"
        }
    return bot_counts

  def swarming_task_step_test_data(self, dimensions):
    """Returns list of bots based on provided dimensions.

    Args:
      dimensions(dict): Dictionary of dimensions
    """
    task_counts = {}
    for dim in dimensions:
      if 'cq' in dim:
        task_counts = {"count": "23", "now": "2020-03-27T19:08:08.207587"}
    return task_counts

  def swarming_task_list_test_data(self, dimensions):
    """Returns list of bots based on provided dimensions.

    Args:
      dimensions(dict): Dictionary of dimensions
    """
    task_counts = {"now": "2020-05-11T20:48:03.437543"}
    task_counts["items"] = [
        {
            "created_ts": "2020-05-11T20:37:01.648454",
        },
        {
            "created_ts": "2020-05-11T15:35:01.648454",
        },
    ]
    return task_counts
