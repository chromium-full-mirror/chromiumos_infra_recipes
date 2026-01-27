# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for calculating greenness metric."""

import collections

from typing import List, OrderedDict, Tuple

from PB.chromiumos import greenness as greenness_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.test_platform.taskstate import TaskState
from PB.chromiumos.greenness import AggregateGreenness

from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult

GreennessTuple = collections.namedtuple(
    'GreennessTuple', ['score', 'build_score', 'critical', 'relevant'])


class GreennessApi(recipe_api.RecipeApi):
  """A module to calculate greenness metric."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._publish_property = properties.publish_property
    self._llfg_exclude_variants = properties.llfg_exclude_variants
    self._builder_greenness_dict: OrderedDict[
        str, GreennessTuple] = collections.OrderedDict()
    self._greenness_markdown = None

  @property
  def greenness_markdown(self) -> str:
    return self._greenness_markdown

  @property
  def builder_greenness_dict(self) -> OrderedDict[str, GreennessTuple]:
    return self._builder_greenness_dict

  def _get_last_greenness(
      self, wait_for_complete: bool) -> OrderedDict[str, OrderedDict[str, str]]:
    """Get the greenness from the previous snapshot.

    Args:
      wait_for_complete: If true, wait until the snapshot orchestrator build is
        completed. Otherwise, only wait until the snapshot orchestrator build
        publishes the build greenness output property. Note that the build will
        publish the build greenness before the test greenness; i.e. this should
        be set true if test greenness is required.

    Returns: OrderedDict mapping builder name to the Greenness message as a
      dict.
    """
    with self.m.step.nest('getting last snapshot greenness') as pres:
      current_snapshot = self.m.cros_infra_config.gitiles_commit
      with self.m.context(cwd=self.m.src_state.build_manifest.path):
        with self.m.step.nest('last snapshot') as sub_pres:
          parents = self.m.git.get_parents(current_snapshot.id)
          last_snapshot = parents.pop().strip()
          sub_pres.logs['current snapshot'] = str(current_snapshot.id)
          sub_pres.logs['last snapshot'] = str(last_snapshot)

        greenness = self.m.buildbucket_stats.get_snapshot_greenness(
            commit=last_snapshot,
            pres=pres,
            end_bbid=self.m.buildbucket.build.id,
            wait_for_complete=wait_for_complete,
        )
        pres.logs['last snapshot greenness'] = str(greenness.items())
        return greenness

  def _is_excluded(self, builder_name: str, exclude_list: List[str]) -> bool:
    """Determine if the builder is an excluded variant."""
    for variant in exclude_list:
      if variant in builder_name:
        return True

    return False

  def _get_build_score_for_tests(self,
                                 greenness_dict: OrderedDict[str,
                                                             GreennessTuple],
                                 key: str) -> int:
    """Get the build score when updating tests info."""
    try:
      return greenness_dict[key].build_score
    except KeyError:
      # If build_score isn't populated, assume 100 since we made it to tests.
      return 100

  def update_build_info(self, builds: List[build_pb2.Build]) -> None:
    """Update greenness with build information.

    If there are any irrelevant builders, this method finds the last snapshot
    and propagates build greenness forward. Note that the last snapshot may not
    have completed, and thus test greenness may not get propagated.

    Args:
      builds: List of builds that have completed.
      wait_for_complete: If true, wait until the snapshot orchestrator build is
        completed. Otherwise, only wait until the snapshot orchestrator build
        publishes the build greenness output property. Note that the build will
        publish the build greenness before the test greenness; i.e. this should
        be set true if test greenness is required.
    """
    if not self._publish_property:
      return

    # Only look up the previous snapshot's greenness if it is required because
    # of irrelevant builders.
    last_greenness = None
    for build in builds:
      builder = build.builder.builder
      green_metric = 100 if build.status == common_pb2.SUCCESS else 0
      critical = build.critical == common_pb2.YES
      if self.m.cros_tags.has_entry('relevance', 'not relevant', build.tags):
        # Failure here should not be fatal to the build.
        with self.m.failures.ignore_exceptions():
          if last_greenness is None:
            last_greenness = self._get_last_greenness(wait_for_complete=False)
          # For irrelevant builders, carry forward greenness from last run.
          # If greenness dict is empty, it means the metric was 0 in the last run.
          builder_greenness = last_greenness.get(
              builder, greenness_pb2.AggregateGreenness.Greenness())
        self._builder_greenness_dict[builder] = GreennessTuple(
            score=builder_greenness.metric,
            build_score=builder_greenness.build_metric, critical=critical,
            relevant=False)
      else:
        self._builder_greenness_dict[builder] = GreennessTuple(
            score=green_metric, build_score=green_metric, critical=critical,
            relevant=True)

  def update_hwtest_info(self, results: List[SkylabResult]) -> None:
    """Update greenness with HW test information.

    Args:
      results: Results of the HW test runs.
    """
    hwtest_dict = {}
    # There is one SkylabResult per builder/suite combo.
    for res in results:
      # Only count if test suite was critical.
      if res.task.test.common.critical.value:
        bt = str(res.task.unit.common.build_target.name)
        builder = str(res.task.unit.common.builder_name)
        # Each child result represents one test_runner build which contains
        # multiple test cases.
        # Shards can be retried in which case they will be represented multiple
        # times in child_results. Only take the best attempt per shard as to not
        # double count or bring down the greenness metric when tests pass on
        # retry.
        shard_name_to_result_mapping = collections.defaultdict(list)
        for shard in res.child_results:
          shard_name_to_result_mapping[shard.name].append(shard)
        test_shards = [
            any(result.state.verdict == TaskState.VERDICT_PASSED
                for result in results)
            for results in shard_name_to_result_mapping.values()
        ]

        prev_shards = hwtest_dict.get((builder, bt), [])
        hwtest_dict[(builder, bt)] = prev_shards + test_shards

    for (builder, bt), test_shards in hwtest_dict.items():
      if test_shards:
        score = int(sum(test_shards) * 100 / len(test_shards))
        builder_score = self._get_build_score_for_tests(
            self._builder_greenness_dict, builder)
        self._builder_greenness_dict[builder] = GreennessTuple(
            score, builder_score, True, True)

  def update_irrelevant_scores(self):
    """Update scores in the greenness dict for irrelevant builds.

    Build scores are propagated forward for irrelevant builds when builds are
    added in update_build_info. update_build_info does not wait for the previous
    snapshot orchestrator to complete, and thus test scores may not be
    propagated forward. This function waits for the previous snapshot
    orchestrator to complete and propagates test scores forward.
    """
    with self.m.step.nest('propagate greenness scores') as pres:
      # Only look up the previous snapshot's greenness if it is required because
      # of irrelevant builders.
      last_greenness = None
      irrelevant_builders = []
      for builder, greenness in self._builder_greenness_dict.items():
        if not greenness.relevant:
          if last_greenness is None:
            last_greenness = self._get_last_greenness(wait_for_complete=True)

          # If greenness dict is empty, it means the metric was 0 in the last run.
          # Only update score since build_score should have already been
          # propagated forward correctly.
          score = last_greenness.get(
              builder, greenness_pb2.AggregateGreenness.Greenness()).metric
          self._builder_greenness_dict[builder] = GreennessTuple(
              score=score,
              build_score=greenness.build_score,
              critical=greenness.critical,
              relevant=greenness.relevant,
          )
          irrelevant_builders.append(builder)

      pres.logs['irrelevant builders'] = irrelevant_builders

  def _set_greenness_markdown(self, aggregate_metric: int,
                              aggregate_build_metric: int):
    """Store string containing greenness info for summary.

    Args:
      aggregate_metric: The aggregate greenness score.
      aggregate_build_metric: The aggregate build-only greenness score.
    """
    self._greenness_markdown = f'Overall Greenness Score: {aggregate_metric}, ' \
        f'Build Only Greenness Score: {aggregate_build_metric}'

  def print_step(self) -> None:
    """Print comprehensive greenness info in a step."""
    with self.m.step.nest('print greenness') as pres:
      if self.builder_greenness_dict:
        log = ''

        # Format the output for humans to quickly check.
        for bazel, text in ((False, 'non-bazel'), (True, 'bazel')):
          if not self.is_green_for_local(bazel):
            builds = sorted(self._get_local_build_greenness(bazel))
            log += '# Failing builders (' + text + ')\n' + ''.join(
                '%s %s\n' % (k, v)
                for k, v in builds
                if v.build_score != 100 and v.critical)
            log += '\n'

        log += '# Full log\n' + ''.join(
            '%s %s\n' % (k, v)
            for k, v in sorted(self.builder_greenness_dict.items()))
      else:
        log = '<no entries>'

      pres.logs['builder_greenness'] = log
      if self._publish_property:
        self.publish_step()

  def publish_step(self) -> None:
    """Publish greenness to output properties."""
    agg_greenness = AggregateGreenness()
    critical_build_scores = []
    critical_scores = []
    with self.m.step.nest('logging irrelevant builder greenness'):
      for builder, green_tuple in self._builder_greenness_dict.items():
        builder_greenness = agg_greenness.builder_greenness.add()
        builder_greenness.builder = builder
        builder_greenness.metric = green_tuple.score
        builder_greenness.build_metric = green_tuple.build_score
        if not green_tuple.relevant:
          builder_greenness.context = AggregateGreenness.Greenness.IRRELEVANT
        if green_tuple.critical:
          # Irrelevant build scores are propagated forward;
          # -1 if not found, skip.
          if green_tuple.build_score != -1:
            critical_build_scores.append(green_tuple.build_score)
          if green_tuple.score != -1:
            critical_scores.append(green_tuple.score)

    agg_green = 0
    agg_build_green = 0
    if critical_scores:
      agg_green = int(sum(critical_scores) / len(critical_scores))
      agg_greenness.aggregate_metric = agg_green
    if critical_build_scores:
      agg_build_green = int(
          sum(critical_build_scores) / len(critical_build_scores))
      agg_greenness.aggregate_build_metric = agg_build_green
    self.m.easy.set_properties_step(greenness=agg_greenness)
    self._set_greenness_markdown(agg_green, agg_build_green)

  def is_green_for_local(self, is_bazel: bool = False) -> bool:
    """Returns whether the current snapshot is green for local builds.

    If there are irrelevant builders for the current snapshot, the greenness
    score from the last relevant build is used. It is assumed that
    builder_greenness_dict is prepopulated (i.e. update_build_info was
    previously called); otherwise, a false positive will be returned.
    """
    builds = self._get_local_build_greenness(is_bazel)
    return not any(
        gt.build_score != 100 and gt.critical is True for _, gt in builds)

  def _get_local_build_greenness(
      self,
      is_bazel: bool,
  ) -> List[Tuple[str, GreennessTuple]]:
    """Returns a filtered list of greenness tuples for local builds.

    It is assumed that builder_greenness_dict is prepopulated (i.e.
    update_build_info was previously called); otherwise, an empty list will
    be returned.
    """
    builds = [(b, gt)
              for (b, gt) in self._builder_greenness_dict.items()
              if not self._is_excluded(b, self._llfg_exclude_variants)]
    return [(b, gt) for (b, gt) in builds if ('-bazel-' in b) == is_bazel]
