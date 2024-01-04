# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for calculating greenness metric."""

import collections

from typing import List, Optional, OrderedDict, Union

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.taskstate import TaskState
from PB.chromiumos.greenness import AggregateGreenness

from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult

GreennessTuple = collections.namedtuple(
    'GreennessTuple', ['score', 'build_score', 'critical', 'relevant'])

# Builder variants to exclude for CQ.
EXCLUDE_VARIANTS = ['-asan-', '-ubsan-', '-kernel-']

# Builder variants to exclude for local greenness.
LOCAL_EXCLUDE_VARIANTS = [
    '-asan-',
    # TODO(b/294303941): Remove once bazel is enabled for local developers.
    '-bazel-',
    '-cpp20-',
    '-kernel-',
    '-kernelnext',
    '-ubsan-',
    '-vm-optimized-',
]


class GreennessApi(recipe_api.RecipeApi):
  """A module to calculate greenness metric."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._publish_property = properties.publish_property
    self._greenness_dict: OrderedDict[
        str, GreennessTuple] = collections.OrderedDict()
    self._builder_greenness_dict: OrderedDict[
        str, GreennessTuple] = collections.OrderedDict()
    self._local_greenness_dict: OrderedDict[
        str, GreennessTuple] = collections.OrderedDict()
    self._last_greenness_dict = None

  @property
  def greenness_dict(self) -> OrderedDict[str, GreennessTuple]:
    return self._greenness_dict

  @property
  def builder_greenness_dict(self) -> OrderedDict[str, GreennessTuple]:
    return self._builder_greenness_dict

  @property
  def local_greenness_dict(self) -> OrderedDict[str, GreennessTuple]:
    return self._local_greenness_dict

  def get_greenness(self, target: str) -> Optional[GreennessTuple]:
    """Get the greenness metric for a specific target.

    Args:
      target: Name of the target.

    Returns: Metric of the target or None if the target wasn't
      launched.
    """
    return self._greenness_dict.get(target, None)

  def get_last_greenness(self,
                         target: str) -> Union[GreennessTuple, OrderedDict]:
    """Get the targetGreenness from the last snapshot run for a given target.

    Args:
      target: Name of the build target.

    Returns: targetGreenness, or an empty OrderedDict if the target, its
      greenness, or the last snapshot wasn't found.
    """
    if self._last_greenness_dict is None:
      with self.m.step.nest('getting last snapshot greenness') as pres:
        current_snapshot = self.m.cros_infra_config.gitiles_commit
        with self.m.context(cwd=self.m.src_state.build_manifest.path):
          with self.m.step.nest('last snapshot') as sub_pres:
            parents = self.m.git.get_parents(current_snapshot.id)
            last_snapshot = parents.pop().strip()
            sub_pres.logs['current snapshot'] = str(current_snapshot.id)
            sub_pres.logs['last snapshot'] = str(last_snapshot)
          self._last_greenness_dict = self.m.buildbucket_stats.get_snapshot_greenness(
              commit=last_snapshot, pres=pres,
              end_bbid=self.m.buildbucket.build.id)
    return self._last_greenness_dict.get(target, collections.OrderedDict())

  def _is_excluded(self, builder_name: str, exclude_list: List[str]) -> bool:
    """Determine if the builder is an excluded variant."""
    for variant in exclude_list:
      if variant in builder_name:
        return True

    return False

  def _get_build_score_for_tests(self,
                                 greenness_dict: OrderedDict[str,
                                                             GreennessTuple],
                                 build_target: str) -> int:
    """Get the build score when updating tests info."""
    try:
      return greenness_dict[build_target].build_score
    except KeyError:
      # If build_score isn't populated, assume 100 since we made it to tests.
      return 100

  def update_build_info(self, builds: List[build_pb2.Build]) -> None:
    """Update greenness with build information.

    Args:
      builds: List of builds that have completed.
    """
    for build in builds:
      bt = str(self.m.cros_infra_config.get_build_target_name(build))
      builder = build.builder.builder
      variant_excluded = self._is_excluded(builder, EXCLUDE_VARIANTS)
      green_metric = 100 if build.status == common_pb2.SUCCESS else 0
      critical = build.critical == common_pb2.YES
      if self.m.cros_tags.has_entry('relevance', 'not relevant', build.tags):
        score, build_score = 0, 0
        # Failure here should not be fatal to the build.
        with self.m.failures.ignore_exceptions():
          # For irrelevant targets, carry forward greenness from last run.
          last_greenness = self.get_last_greenness(bt)
          # If greenness dict is empty, it means the metric was 0 in the last run.
          score = int(last_greenness.get('metric', 0))
          build_score = int(last_greenness.get('buildMetric', 0))
        self._builder_greenness_dict[builder] = GreennessTuple(
            score=score, build_score=build_score, critical=critical,
            relevant=False)
        if not variant_excluded:
          self._greenness_dict[bt] = GreennessTuple(score=score,
                                                    build_score=build_score,
                                                    critical=critical,
                                                    relevant=False)
      else:
        self._builder_greenness_dict[builder] = GreennessTuple(
            score=green_metric, build_score=green_metric, critical=critical,
            relevant=True)
        if not variant_excluded:
          self._greenness_dict[bt] = GreennessTuple(score=green_metric,
                                                    build_score=green_metric,
                                                    critical=critical,
                                                    relevant=True)

  def populate_local_build_info(self, builds: List[build_pb2.Build]) -> None:
    """Populate the local greenness dict with build information.

    For local build greenness, we want to track by build target and variant
    rather than just build target (e.g. amd64-generic-asan is tracked
    separately from amd64-generic).

    Args:
      builds: List of builds that have completed.
    """
    for build in builds:
      builder = build.builder.builder
      if self._is_excluded(builder, LOCAL_EXCLUDE_VARIANTS):
        continue
      critical = build.critical == common_pb2.YES
      if self.m.cros_tags.has_entry('relevance', 'not relevant', build.tags):
        # For irrelevant build targets, mark the score and build_score as -1
        # so the scores can be updated using a relevant build from an earlier
        # snapshot.
        self._local_greenness_dict[builder] = GreennessTuple(
            score=-1, build_score=-1, critical=critical, relevant=False)
      else:
        green_metric = 100 if build.status == common_pb2.SUCCESS else 0
        self._local_greenness_dict[builder] = GreennessTuple(
            score=green_metric, build_score=green_metric, critical=critical,
            relevant=True)

  def update_hwtest_info(self, results: List[SkylabResult]) -> None:
    """Update greenness with HW test information.

    Args:
      results: Results of the HW test runs.
    """
    hwtest_dict = {}
    for res in results:
      # Only count if test suite was critical.
      if res.task.test.common.critical.value:
        bt = str(res.task.unit.common.build_target.name)
        builder = str(res.task.unit.common.builder_name)
        test_cases = [
            r.state.verdict == TaskState.VERDICT_PASSED
            for r in res.child_results
        ]
        prev_cases = hwtest_dict.get((builder, bt), [])
        hwtest_dict[(builder, bt)] = prev_cases + test_cases

    for (builder, bt), test_cases in hwtest_dict.items():
      if test_cases:
        score = int(sum(test_cases) * 100 / len(test_cases))
        build_score = self._get_build_score_for_tests(self._greenness_dict, bt)
        self._greenness_dict[bt] = GreennessTuple(score, build_score, True,
                                                  True)
        builder_score = self._get_build_score_for_tests(
            self._builder_greenness_dict, builder)
        self._builder_greenness_dict[builder] = GreennessTuple(
            score, builder_score, True, True)
        local_build_score = self._get_build_score_for_tests(
            self._local_greenness_dict, bt)
        self._local_greenness_dict[bt] = GreennessTuple(score,
                                                        local_build_score, True,
                                                        True)

  def update_vmtest_info(self, results: List[build_pb2.Build]) -> None:
    """Update greenness with VM test information.

    Args:
      results: Builds of the VM test runs.
    """
    for res in results:
      bt = str(self.m.cros_infra_config.get_build_target_name(res))
      if 'greenness' in res.output.properties:
        builder = str(res.input.properties['name']).split('.', maxsplit=1)[0]
        greenness = int(res.output.properties['greenness'])
        build_score = self._get_build_score_for_tests(self._greenness_dict, bt)
        self._greenness_dict[bt] = GreennessTuple(greenness, build_score, True,
                                                  True)
        builder_score = self._get_build_score_for_tests(
            self._builder_greenness_dict, builder)
        self._builder_greenness_dict[builder] = GreennessTuple(
            greenness, builder_score, True, True)
        local_build_score = self._get_build_score_for_tests(
            self._local_greenness_dict, bt)
        self._local_greenness_dict[bt] = GreennessTuple(greenness,
                                                        local_build_score, True,
                                                        True)

  def update_irrelevant_builds_scores(
      self, builds: List[build_pb2.Build],
      greenness_dict: OrderedDict[str, GreennessTuple]) -> None:
    """Update scores in the greenness dict for irrelevant builds.

    Args:
      builds: List of builds that have completed.
      greenness_dict: The greenness dict to update.
    """
    irrelevant_builds = []
    for b in greenness_dict:
      green_tuple = greenness_dict[b]
      if not green_tuple.relevant and green_tuple.build_score == -1:
        irrelevant_builds.append(b)
    for ib in irrelevant_builds:
      build = next((b for b in builds if ib == b.builder.builder), None)
      if build and not self.m.cros_tags.has_entry('relevance', 'not relevant',
                                                  build.tags):
        green_metric = 100 if build.status == common_pb2.SUCCESS else 0
        critical = build.critical == common_pb2.YES
        greenness_dict[ib] = GreennessTuple(score=green_metric,
                                            build_score=green_metric,
                                            critical=critical, relevant=False)

  def print_step(self) -> None:
    """Print comprehensive greenness info in a step."""
    with self.m.step.nest('print greenness') as pres:
      pres.logs['greenness'] = str(self._greenness_dict)
      pres.logs['builder_greenness'] = str(self.builder_greenness_dict)
      if self._publish_property:
        self.publish_step()

  def publish_step(self) -> None:
    """Publish greenness to output properties."""
    agg_greenness = AggregateGreenness()
    critical_build_scores = []
    critical_scores = []
    with self.m.step.nest('logging irrelevant build target greenness') as pres:
      for bt, green_tuple in self._greenness_dict.items():
        target_greenness = agg_greenness.target_greenness.add()
        target_greenness.target = bt
        target_greenness.metric = green_tuple.score
        target_greenness.build_metric = green_tuple.build_score
        if not green_tuple.relevant:
          target_greenness.context = AggregateGreenness.Greenness.IRRELEVANT
        with self.m.failures.ignore_exceptions():
          if not green_tuple.relevant:
            pres.logs[
                bt] = f'Score: {green_tuple.score}, Build score: {green_tuple.build_score}'
        if green_tuple.critical:
          # Irrelevant build scores are propagated forward; -1 if not found.
          if green_tuple.relevant or green_tuple.build_score != -1:
            critical_build_scores.append(green_tuple.build_score)
          if green_tuple.relevant:
            critical_scores.append(green_tuple.score)

      for builder, green_tuple in self._builder_greenness_dict.items():
        builder_greenness = agg_greenness.builder_greenness.add()
        builder_greenness.builder = builder
        builder_greenness.metric = green_tuple.score
        builder_greenness.build_metric = green_tuple.build_score
        if not green_tuple.relevant:
          builder_greenness.context = AggregateGreenness.Greenness.IRRELEVANT

    if critical_scores:
      agg_greenness.aggregate_metric = int(
          sum(critical_scores) / len(critical_scores))
    if critical_build_scores:
      agg_greenness.aggregate_build_metric = int(
          sum(critical_build_scores) / len(critical_build_scores))
    self.m.easy.set_properties_step(greenness=agg_greenness)

  def get_aggregate_builder_local_greenness(
      self, snapshot_commit: str, snapshot_builder_names: List[str]) -> int:
    """Get the aggregate greenness for the given builders on the given commit.

    Returns the average greenness score for the given builders on the given
    snapshot.

    Note:
      * If there is no greenness reported for a given builder it is given a
       score of 0.

    Args:
      snapshot_commit: The snapshot commit to use when calculating greenness.
      snapshot_builder_names: The names of the builder for which to get an
          aggregate greenness calculation.

    Raises:
      StepFailure if snapshot_builder_names is empty.
    """
    with self.m.step.nest('get greenness for specified builders') as pres:
      if not snapshot_builder_names:
        raise recipe_api.StepFailure('snapshot_builder_names cannot be empty')

      local_greenness = self.m.buildbucket_stats.get_snapshot_greenness(
          commit=snapshot_commit, retries=0, use_local_greenness=True,
          pres=pres)
      if not local_greenness:
        pres.step_text = f'cound not find greeness for snapshot {snapshot_commit}'
        return 0

      running_greenness = 0
      missing_greenness = []
      for b in snapshot_builder_names:
        build_greenness_tuple = local_greenness.get(b)

        if not build_greenness_tuple:
          missing_greenness.append(b)
          continue

        build_greenness_tuple = GreennessTuple(*build_greenness_tuple)
        running_greenness += build_greenness_tuple.build_score

      agg_greenness = int(running_greenness / len(snapshot_builder_names))
      step_text = f'greenness score: {agg_greenness}'

      if missing_greenness:
        step_text += f'. Unable to find local greenness for {len(missing_greenness)} target(s)'
        pres.logs['missing greenness'] = sorted(missing_greenness)

      pres.step_text = step_text
      return agg_greenness
