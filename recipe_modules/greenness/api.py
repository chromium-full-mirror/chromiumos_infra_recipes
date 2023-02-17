# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for calculating greenness metric."""

from collections import namedtuple
from collections import OrderedDict

from typing import OrderedDict as OrderedDict_type

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.taskstate import TaskState
from PB.chromiumos.greenness import AggregateGreenness

from recipe_engine import recipe_api

GreennessTuple = namedtuple('GreennessTuple',
                            ['score', 'build_score', 'critical', 'relevant'])
EXCLUDE_VARIANTS = ['-asan-', '-ubsan-', '-kernel-']


class GreennessApi(recipe_api.RecipeApi):
  """A module to calculate greenness metric."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._publish_property = properties.publish_property
    self._greenness_dict: OrderedDict_type[str, GreennessTuple] = OrderedDict()

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

  def _is_excluded(self, builder_name):
    for variant in EXCLUDE_VARIANTS:
      if variant in builder_name:
        return True

    return False

  def update_build_info(self, builds):
    """Update Grenness with build information.

    Args:
      builds([Build]): Buildbucket.Build objects of builds that
      have completed.
    """
    for build in builds:
      bt = str(self.m.cros_infra_config.get_build_target_name(build))
      if self._is_excluded(build.builder.builder):
        continue
      green_metric = 100 if build.status == common_pb2.SUCCESS else 0
      critical = build.critical == common_pb2.YES
      if self.m.cros_tags.has_entry('relevance', 'not relevant', build.tags):
        self._greenness_dict[bt] = GreennessTuple(score=0, build_score=0,
                                                  critical=critical,
                                                  relevant=False)
      else:
        self._greenness_dict[bt] = GreennessTuple(green_metric, green_metric,
                                                  critical, True)

  def update_hwtest_info(self, results):
    """Update Grenness with HW test information.

    Args:
      results([SkylabResult]): Results of the HW test runs.
    """
    hwtest_dict = {}
    for res in results:
      # Only count if test suite was critical.
      if res.task.test.common.critical.value:
        bt = res.task.unit.common.build_target.name
        test_cases = [
            r.state.verdict == TaskState.VERDICT_PASSED
            for r in res.child_results
        ]
        prev_cases = hwtest_dict.get(bt, [])
        hwtest_dict[bt] = prev_cases + test_cases

    for bt, test_cases in hwtest_dict.items():
      if test_cases:
        score = int(sum(test_cases) * 100 / len(test_cases))
        # If build_score isn't populated, assume 100 since we made it to tests.
        try:
          build_score = self._greenness_dict[str(bt)].build_score
        except KeyError:
          build_score = 100
        self._greenness_dict[str(bt)] = GreennessTuple(score, build_score, True,
                                                       True)

  def update_vmtest_info(self, results):
    """Update Grenness with VM test information.

    Args:
      results([build_pb2.Build]): Builds of the VM test runs.
    """
    for res in results:
      bt = self.m.cros_infra_config.get_build_target_name(build=res)
      if 'greenness' in res.output.properties:
        greenness = res.output.properties['greenness']
        # If build_score isn't populated, assume 100 since we made it to tests.
        try:
          build_score = self._greenness_dict[str(bt)].build_score
        except KeyError:
          build_score = 100
        self._greenness_dict[str(bt)] = GreennessTuple(
            int(greenness), build_score, True, True)

  def print_step(self):
    """Print comprehensive greenness info in a step."""
    with self.m.step.nest('print greenness') as pres:
      pres.logs['greenness'] = str(self._greenness_dict)
      if self._publish_property:
        self.publish_step()

  def publish_step(self):
    """Publish greenness to output properties."""
    agg_greenness = AggregateGreenness()
    critical_build_scores = []
    critical_scores = []
    for bt, green_tuple in self._greenness_dict.items():
      target_greenness = agg_greenness.target_greenness.add()
      target_greenness.target = bt
      target_greenness.metric = green_tuple.score
      target_greenness.build_metric = green_tuple.build_score
      if not green_tuple.relevant:
        target_greenness.context = AggregateGreenness.Greenness.IRRELEVANT
      if green_tuple.critical and green_tuple.relevant:
        critical_build_scores.append(green_tuple.build_score)
        critical_scores.append(green_tuple.score)

    if critical_scores:
      agg_greenness.aggregate_metric = int(
          sum(critical_scores) / len(critical_scores))
      agg_greenness.aggregate_build_metric = int(
          sum(critical_build_scores) / len(critical_build_scores))
    self.m.easy.set_properties_step(greenness=agg_greenness)
