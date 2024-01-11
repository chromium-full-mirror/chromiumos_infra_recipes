# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions implementing looks for green."""

from collections import namedtuple
import datetime
from typing import Any, Dict, List, Optional

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenProperties
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStats
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStatus

from google.protobuf import timestamp_pb2

from recipe_engine import recipe_api
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

Snapshot = namedtuple('Snapshot', [
    'bbid',
    'commit_sha',
    'start_time',
    'end_time',
    'agg_green',
    'approx_snap_age_hours',
    'builder_greenness',
    'local_greenness',
])


class LooksForGreenApi(recipe_api.RecipeApi):
  """A module to look for green snapshots."""

  # A git footer that can be included in commit messages to tell the cq run to
  # disallow looks for green behavior.
  DISALLOW_LOOKS_FOR_GREEN_FOOTER = 'Disallow-Looks-For-Green'

  def __init__(self, properties: LooksForGreenProperties,
               **kwargs: Any) -> None:
    super().__init__(**kwargs)
    self.enable_looks_for_green = properties.enable_looks_for_green
    self._max_concurrent_snapshot_runs = properties.max_concurrent_snapshot_runs or 25
    self._lookback_hours = properties.lookback_hours or 10
    self._greenness_threshold = properties.greenness_threshold or 80
    self.use_complete_snapshot = properties.use_complete_snapshot
    self._use_scored_over_minted = properties.use_scored_over_minted
    self._stats = LooksForGreenStats()
    self._now = None
    self._seconds_now = None
    self._should_lfg = None
    self._related_changes_to_apply = None

  @property
  def now_utc(self) -> datetime.datetime:
    """Returns the current UTC time.

    Initialized once and used throughout for any time calculations. Zero out
    the microseconds to use seconds as level of precision.
    """
    if not self._now:
      self._now = self.m.time.utcnow().replace(microsecond=0)
    # Synchronize timing.
    if not self._seconds_now:
      self._seconds_now = int(self.m.time.time())
    return self._now

  @property
  def seconds_utc(self) -> int:
    """Returns the current UTC time in seconds.

    Initialized once and used throughout for any time calculations. Cast to int to use seconds as level of precision.
    """
    if not self._seconds_now:
      self._seconds_now = int(self.m.time.time())
    # Synchronize timing.
    if not self._now:
      self._now = self.m.time.utcnow().replace(microsecond=0)
    return self._seconds_now

  @property
  def stats(self) -> LooksForGreenStats:
    """Returns looks for green stats"""
    return self._stats

  @property
  def use_scored_over_minted(self) -> bool:
    """Returns use_scored_over_minted property."""
    return self._use_scored_over_minted

  @property
  def _greenness_bucket(self) -> str:
    """Returns bucket to query for greenness."""
    return 'staging' if self.m.cros_infra_config.is_staging else 'postsubmit'

  @property
  def _greenness_builder(self) -> str:
    """Returns builder to query for greenness."""
    prefix = 'staging-' if self.m.cros_infra_config.is_staging else ''
    return f'{prefix}snapshot-orchestrator'

  @property
  def related_changes_to_apply(self) -> Dict:
    return self._related_changes_to_apply

  @related_changes_to_apply.setter
  def related_changes_to_apply(self, related_changes_to_apply):
    self._related_changes_to_apply = related_changes_to_apply

  def should_lfg(self, gerrit_changes: List[GerritChange]) -> bool:
    """Returns whether looks for green logic should be run."""
    if self._should_lfg is None:
      # This check shouldn't be fatal to a build.
      self._should_lfg = False
      with self.m.failures.ignore_exceptions():
        with self.m.step.nest('check should look for green') as pres:
          # Don't perform extra checks if LFG is not enabled.
          if not self.m.looks_for_green.enable_looks_for_green:
            self._should_lfg = False
            return self._should_lfg

          # Only look for green in CQ.
          if not self.m.cq.active:
            pres.step_text = 'Skipping looks for green outside of CQ'
            self._should_lfg = False
            return self._should_lfg
          disallow = self.found_disallow_lfg_footer(gerrit_changes)
          if disallow:
            self._stats.status = LooksForGreenStatus.STATUS_SKIPPED_DISALLOW
          has_merge_commit = any(
              self.m.gerrit.is_merge_commit(c.change, c.host)
              for c in gerrit_changes)
          if has_merge_commit:
            self._stats.status = LooksForGreenStatus.STATUS_SKIPPED_MERGE_COMMIT
          self._should_lfg = (not disallow and not has_merge_commit)
          should_lfg_log = (f'Found disallow footer: {disallow}, Found has'
                            f' merge commit: {has_merge_commit}')
          # TODO(b/276363760): Don't LFG with Cq-Depend until supported.
          if self._should_lfg:
            with self.m.step.nest('check if CL uses Cq-Depend'):
              if self.m.git_footers.get_footer_values(gerrit_changes,
                                                      'Cq-Depend'):
                self._should_lfg = False
                self._stats.status = LooksForGreenStatus.STATUS_SKIPPED_CQ_DEPEND
                should_lfg_log += '. Found Cq-Depend footer'
                pres.logs['Cq-Depend footer'] = (
                    'Found Cq-Depend footer. Skipping'
                    ' looks for green.')
          # TODO(b/276363760): Don't LFG with stacked changes that aren't
          # included.
          if self._should_lfg:
            with self.m.step.nest(
                'check if CL has related changes not included'):
              if self.related_changes_to_apply:
                self._should_lfg = False
                self._stats.status = LooksForGreenStatus.STATUS_SKIPPED_STACKED_CHANGES
                should_lfg_log += '. Found relation chain with depended changes not included'
                pres.logs['Relation chain'] = (
                    f'Found CL(s) part of a relation chain. Some depended changes are not included: {self.related_changes_to_apply}. Skipping'
                    ' looks for green.')
          if not self._should_lfg:
            should_lfg_log += '. Using original snapshot.'
            self.m.easy.set_properties_step(looks_for_green=self.stats)
          pres.logs['should_lfg'] = should_lfg_log
    return self._should_lfg

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=1))
  def _get_snapshots(
      self,
      limit: Optional[int] = None,
      latest_start: Optional[timestamp_pb2.Timestamp] = None,
      bucket: Optional[str] = None,
      builder: Optional[str] = None,
  ) -> List[build_pb2.Build]:
    """Get snapshot builds within the lookback period.

    Optionally specify a limit of builds to return. Optionally specify a
    latest_start time in UTC for builds.

    Args:
      limit: A limit on the number of builds to return.
      latest_start: The latest start time of snapshot orchestrators to consider,
        or the current time if not set.
      bucket: If specified, the bucket to search in. Defaults to
        self._greenness_bucket.
      builder: If specified, the builder to search for. Defaults to
        self._greenness_builder.

    Returns:
      Snapshot builds found within the lookback period.
    """
    fields = frozenset({
        'id', 'input.gitiles_commit.id', 'output.properties', 'start_time',
        'end_time', 'status'
    })
    # Look back from latest_start if specified, otherwise from current time.
    if latest_start:
      latest_seconds = latest_start.ToSeconds()
      predicate = builds_service_pb2.BuildPredicate(
          create_time=common_pb2.TimeRange(
              start_time=timestamp_pb2.Timestamp(
                  seconds=latest_seconds - self._lookback_hours * 60 * 60,
              ), end_time=latest_start))
    else:
      latest_seconds = self.seconds_utc
      predicate = builds_service_pb2.BuildPredicate(
          create_time=common_pb2.TimeRange(
              start_time=timestamp_pb2.Timestamp(
                  seconds=latest_seconds - self._lookback_hours * 60 * 60,
              )))
    predicate.builder.project = self.m.buildbucket.build.builder.project
    predicate.builder.bucket = bucket or self._greenness_bucket
    predicate.builder.builder = builder or self._greenness_builder
    return self.m.buildbucket.search([predicate], limit=limit, fields=fields,
                                     timeout=60)

  def _parse_snapshot_result(self,
                             snapshot_result: build_pb2.Build) -> Snapshot:
    """Parse buildbucket return into Snapshot NamedTuple."""
    start_time = datetime.datetime.utcfromtimestamp(
        snapshot_result.start_time.seconds)
    end_time = datetime.datetime.utcfromtimestamp(
        snapshot_result.end_time.seconds)
    out_props = snapshot_result.output.properties
    try:
      agg_green = int(out_props['greenness']['aggregateBuildMetric'])
    except ValueError:
      agg_green = -1
    try:
      builder_greenness = self.m.buildbucket_stats.reformat_greenness_dict(
          out_props['greenness']['builderGreenness'])
    except ValueError:
      builder_greenness = {}
    local_greenness = self.m.buildbucket_stats.parse_local_greenness(out_props)
    approx_snap_age_hours = self.calc_approx_snap_age_hours(start_time)
    return Snapshot(
        bbid=snapshot_result.id,
        commit_sha=snapshot_result.input.gitiles_commit.id,
        start_time=start_time,
        end_time=end_time,
        agg_green=agg_green,
        approx_snap_age_hours=approx_snap_age_hours,
        builder_greenness=builder_greenness,
        local_greenness=local_greenness,
    )

  def _set_snapshot_stats(
      self,
      snapshot_stats: Snapshot,
      suggested: bool = False,
  ) -> None:
    """Set output stats using LooksForGreenStats proto fields.

    When suggested is True, populate stats for the snapshot that CQ Looks
    recommends to use. Otherwise, populate state for the latest snapshot that
    has go/greenness properties set.
    """
    if not suggested:
      stats = self._stats.latest_scored
    else:
      stats = self._stats.suggested

    stats.snap_orch_greenness = snapshot_stats.agg_green
    stats.approx_snap_age_hours = snapshot_stats.approx_snap_age_hours
    stats.snap_orch_bbid = snapshot_stats.bbid
    stats.snap_commit_sha = snapshot_stats.commit_sha

  def _get_latest_scored_snapshot(
      self, build_results: List[build_pb2.Build]) -> Optional[build_pb2.Build]:
    """Find the latest snapshot with a greenness score."""
    for build in build_results:
      if 'greenness' in build.output.properties and \
      'aggregateBuildMetric' in build.output.properties['greenness']:
        return build
    return None

  def get_latest_snapshot_greenness(
      self,
      bucket: Optional[str] = None,
      builder: Optional[str] = None,
  ) -> Optional[Snapshot]:
    """Returns the latest scored Snapshot.

    Or None if no latest scored snapshot is found.

    If the latest snapshot-orchestrator has just started, we won't have
    greenness yet, so look back at the most recent snapshot-orchestrator (of
    the self._max_concurrent_snapshot_runs most recent runs) that does have
    greenness populated.

    Args:
      bucket: If specified, the bucket to search in. Defaults to
        self._greenness_bucket.
      builder: If specified, the builder to search for. Defaults to
        self._greenness_builder.

    Returns:
      Snapshot from the latest scored snapshot-orchestrator, or None if not
        found.
    """
    with self.m.step.nest(
        'checking latest scored snapshot greenness') as presentation:
      results = self._get_snapshots(limit=self._max_concurrent_snapshot_runs,
                                    bucket=bucket, builder=builder)
      scored_snapshot = self._get_latest_scored_snapshot(results)
      if not scored_snapshot:
        presentation.logs['latest scored snapshot greenness'] = (
            'found no scored snapshot in the latest '
            f'{self._max_concurrent_snapshot_runs} builds')
        return None
      snapshot_stats = self._parse_snapshot_result(scored_snapshot)
      presentation.logs['latest scored snapshot greenness'] = (
          'latest scored snapshot-orchestrator '
          f'go/bbid/{snapshot_stats.bbid} has aggregate greenness of '
          f'{snapshot_stats.agg_green}. Start time: {snapshot_stats.start_time}'
          f' End time: {snapshot_stats.end_time}. The current time is '
          f'{self.now_utc}')
      self._set_snapshot_stats(snapshot_stats)
      return snapshot_stats

  def calc_approx_snap_age_hours(self,
                                 orch_start_time: datetime.datetime) -> int:
    """Returns how many hours age the latest scored snap-orch started.

    This is used as an approximation of snapshot manifest age since a
    snapshot-orchestrator run starts within ~30 minutes of snapshot creation.

    Returns:
      Approx age in hours of snapshot used by latest scored snap-orch.
    """
    delta = self.now_utc - orch_start_time
    days, seconds = delta.days, delta.seconds
    approx_snap_age_hours = days * 24 + seconds / 3600
    return round(approx_snap_age_hours)

  def _get_latest_greenest_snapshot(
      self, parsed_results: List[Snapshot]) -> Optional[Snapshot]:
    """Get the latest greenest snapshot from a list of buildbucket snapshots.

    Return None if no green snapshot exists.
    """
    green_results = list(
        filter(lambda d: d.agg_green >= self._greenness_threshold,
               parsed_results))
    if not green_results:
      return None
    max_greenness = max([r.agg_green for r in parsed_results])
    greenest_results = list(
        filter(lambda d: d.agg_green == max_greenness, green_results))
    latest_snap = max(greenest_results, key=lambda k: k.start_time)
    return latest_snap

  def find_green_snapshot(
      self,
      latest_start: Optional[timestamp_pb2.Timestamp] = None,
      bucket: Optional[str] = None,
      builder: Optional[str] = None,
  ) -> Optional[Snapshot]:
    """Find a green snapshot within the lookback period if one exists.

    Optionally specify a latest_start time in UTC for builds.

    Args:
      latest_start: The latest start time of snapshot orchestrators to consider,
        or the current time if not set.
      bucket: If specified, the bucket to search in. Defaults to
        self._greenness_bucket.
      builder: If specified, the builder to search for. Defaults to
        self._greenness_builder.

    Returns:
      A green snapshot, if one was found.
    """
    with self.m.step.nest('find green snapshot') as presentation:
      results = self._get_snapshots(latest_start=latest_start, bucket=bucket,
                                    builder=builder)
      parsed_results = []
      for result in results:
        parsed_results.append(self._parse_snapshot_result(result))
      green = self._get_latest_greenest_snapshot(parsed_results)
      if green:
        presentation.logs['latest green'] = (
            f'Found green snapshot: {green.commit_sha} with '
            f'greenness {green.agg_green} and {green.approx_snap_age_hours} '
            'hours old.')
        self._set_snapshot_stats(green, suggested=True)
        self._stats.status = LooksForGreenStatus.STATUS_RAN_OLDER
        self.m.easy.set_properties_step(looks_for_green=self.stats)
      else:
        presentation.logs['latest green'] = (
            'Found no snapshot of at least '
            f'{self._greenness_threshold} greenness within the last '
            f'{self._lookback_hours} hours.')
        self._stats.status = LooksForGreenStatus.STATUS_FOUND_NONE
        self.m.easy.set_properties_step(looks_for_green=self.stats)
      return green

  def is_snap_orch_green(self) -> bool:
    """Returns whether the latest scored snapshot-orchestrator greenness is

    higher than greenness threshold.

    Returns:
      Whether latest scored snap-orch run is green
    """
    latest_greenness = self.get_latest_snapshot_greenness()
    is_snap_orch_green = latest_greenness is not None and latest_greenness.agg_green >= self._greenness_threshold
    self._stats.latest_scored.is_snap_orch_green = is_snap_orch_green
    # This logic is a bit brittle as it assumes that the caller is not going to
    # turn around and choose a different snapshot.
    if is_snap_orch_green:
      self._stats.status = (
          LooksForGreenStatus.STATUS_RAN_OLDER if self._use_scored_over_minted
          else LooksForGreenStatus.STATUS_RAN_LATEST_MINTED)
    self.m.easy.set_properties_step(looks_for_green=self.stats)
    return is_snap_orch_green

  def found_disallow_lfg_footer(
      self, gerrit_changes: List[common_pb2.GerritChange]) -> bool:
    """Check the incoming gerrit changes for disallow looks for green footer.

    Args:
      gerrit_changes: The gerrit changes.

    Returns:
      Whether the disallow LFG footer is included and not set to false.
    """
    with self.m.step.nest('check disallow looks for green') as presentation:
      found_disallow = False
      git_footers = self.m.git_footers.get_footer_values(
          gerrit_changes, self.DISALLOW_LOOKS_FOR_GREEN_FOOTER)
      presentation.logs['check disallow looks for green'] = (
          f'Found {self.DISALLOW_LOOKS_FOR_GREEN_FOOTER} footers: '
          f'{sorted(git_footers)}')
      for git_footer in git_footers:
        if git_footer.lower() != 'false':
          found_disallow = True
          presentation.step_text = (
              f'Found {self.DISALLOW_LOOKS_FOR_GREEN_FOOTER}. Disabling looks '
              'for green behavior.')

      return found_disallow

  def is_green_for_local(self) -> bool:
    """Returns whether the current snapshot is green for local builds.

    If there are irrelevant builders for the current snapshot, look at previous
    snapshots to find the last relevant build and update the greenness scores.
    """
    current_build = self.m.buildbucket.build
    with self.m.step.nest('check current snapshot build') as presentation:
      current_child_builds = self.get_child_builds(current_build)
      self.m.greenness.populate_local_build_info(current_child_builds)
      presentation.logs['current snapshot greenness'] = str(
          self.m.greenness.local_greenness_dict)

    with self.m.step.nest('get previous snapshot builds'):
      # Filter the last n builds to builds that were created before the current
      # build.
      prev_snapshot_builds = self._get_snapshots(
          limit=20, latest_start=current_build.create_time)

    with self.m.step.nest(
        'update with previous snapshot builds') as presentation:
      update_log = ''
      for snapshot in prev_snapshot_builds:
        # Only update for irrelevant builders that have not yet been updated
        # (i.e. build_score is -1).
        if any(gt.build_score == -1 and gt.relevant is False
               for gt in self.m.greenness.local_greenness_dict.values()):
          prev_child_builds = self.get_child_builds(snapshot)
          self.m.greenness.update_irrelevant_builds_scores(
              prev_child_builds, self.m.greenness.local_greenness_dict)
          update_log += (
              'Updated greenness dict using snapshot: '
              f'{snapshot.input.gitiles_commit.id}\n'
              f'Updated greenness dict: {self.m.greenness.local_greenness_dict}\n'
          )
      presentation.logs['updated local greenness'] = update_log

    return not any(gt.build_score != 100 and gt.critical is True
                   for gt in self.m.greenness.local_greenness_dict.values())

  @exponential_retry(retries=3, delay=datetime.timedelta(seconds=1))
  def get_child_builds(self,
                       current_build: build_pb2.Build) -> List[build_pb2.Build]:
    """Get the child builds of the current build."""
    predicate = builds_service_pb2.BuildPredicate(
        tags=self.m.buildbucket.tags(
            parent_buildbucket_id=str(current_build.id)))
    predicate.builder.project = current_build.builder.project
    fields = frozenset({'builder', 'critical', 'id', 'status', 'tags'})
    return self.m.buildbucket.search(predicate, fields=fields)
