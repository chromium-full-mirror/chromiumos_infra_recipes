# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for calculating greenness metric."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.taskstate import TaskState

from recipe_engine import recipe_api


class GreennessApi(recipe_api.RecipeApi):
  """A module to calculate greenness metric."""

  def __init__(self, *args, **kwargs):
    super(GreennessApi, self).__init__(*args, **kwargs)
    self._greenness_dict = {}

  @property
  def greenness_dict(self):
    return self._greenness_dict

  def get_greenness(self, target):
    """Returns the greenness metric for a specific target.

    Args:
      target (str): Name of the target.

    Returns: Metric of the target or None if the target wasn't
    launched.
    """
    return self._greenness_dict.get(target, None)

  def update_build_info(self, builds):
    """Update Grenness with build information.

    Args:
      builds([Build]): Buildbucket.Build objects of builds that
      have completed.
    """
    for build in builds:
      bt = self.m.cros_infra_config.get_build_target_name(build)
      green_metric = 100 if build.status == common_pb2.SUCCESS else 0
      self._greenness_dict[bt] = green_metric

  def update_hwtest_info(self, results):
    """Update Grenness with HW test information.

    Args:
      results([SkylabResult]): Results of the HW test runs.
    """
    hwtest_dict = {}
    for res in results:
      bt = res.task.unit.common.build_target.name
      test_cases = [
          r.state.verdict == TaskState.VERDICT_PASSED for r in res.child_results
      ]
      prev_cases = hwtest_dict.get(bt, [])
      hwtest_dict[bt] = prev_cases + test_cases

    for bt, test_cases in hwtest_dict.items():
      if test_cases:
        self._greenness_dict[bt] = int(sum(test_cases) * 100 / len(test_cases))

  def print_step(self):
    """Print comprehensive greenness info in a step."""
    with self.m.step.nest('print greenness') as pres:
      pres.logs['greenness'] = str(self._greenness_dict)
