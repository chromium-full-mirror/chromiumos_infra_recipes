# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions implementing looks for green."""

import dataclasses
import datetime
from typing import Any, Dict, List, Optional

from PB.chromiumos import greenness as greenness_pb2
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

# The default lookback time.
DEFAULT_LOOKBACK_HOURS = 10

@dataclasses.dataclass
class Snapshot:
  # The snapshot-orchestrator's buildbucket id.
  bbid: str

  # The commit SHA of the manifest-internal snapshot ref.
  commit_sha: str

  # The snapshot-orchestrator's start_time.
  start_time: timestamp_pb2.Timestamp

  # The snapshot-orchestrator's end_time.
  end_time: timestamp_pb2.Timestamp

  # The aggregate build score.
  agg_green: int

  # The approximate age of the snapshot.
  approx_snap_age_hours: int

  # Dict of per-builder greenness.
  builder_greenness: Dict[str, greenness_pb2.AggregateGreenness.Greenness]

  # The aggregate build score for the requested builders. If specific builders
  # were not requested, then this will be equal to agg_green.
  requested_builders_agg_green: int

  # Optional, the subset of builders considered when aggregating greenness.
  requested_builders: Optional[List[str]] = None

  # Any builders which were requested but did not have greenness published.
  # Only relevant if requested_builders is non-empty.
  requested_builders_missing_from_snapshot: Optional[List[str]] = None


class LooksForGreenApi(recipe_api.RecipeApi):
  """A module to look for green snapshots."""

  # A git footer that can be included in commit messages to tell the cq run to
  # disallow looks for green behavior.
  DISALLOW_LOOKS_FOR_GREEN_FOOTER = 'Disallow-Looks-For-Green'

  def __init__(self, properties: LooksForGreenProperties,
               **kwargs: Any) -> None:
    super().__init__(**kwargs)
    self.enable_looks_for_green = properties.enable_looks_for_green
    self._lookback_hours = properties.lookback_hours or DEFAULT_LOOKBACK_HOURS
    self._greenness_threshold = properties.greenness_threshold or 80
    self.use_complete_snapshot = properties.use_complete_snapshot
    self._stats = LooksForGreenStats()
    self._now = None
    self._seconds_now = None

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
  def lookback_hours(self) -> float:
    """Returns lookback hours"""
    return self._lookback_hours

  @lookback_hours.setter
  def lookback_hours(self, lookback_hours):
    self._lookback_hours = lookback_hours
    self._stats.lookback_hours = self._lookback_hours
    self.set_stats()

  @property
  def _greenness_bucket(self) -> str:
    """Returns bucket to query for greenness."""
    return 'staging' if self.m.cros_infra_config.is_staging else 'postsubmit'

  @property
  def _greenness_builder(self) -> str:
    """Returns builder to query for greenness."""
    prefix = 'staging-' if self.m.cros_infra_config.is_staging else ''
    return f'{prefix}snapshot-orchestrator'

  def set_stats(self):
    """Sets the LFG output property based on latest info."""
    self.m.easy.set_properties_step(looks_for_green=self.stats)

  def _test_submission_data(self):
    kwargs = {}
    eight_hours_ago = self.m.time.utcnow() - datetime.timedelta(hours=8)
    kwargs['submitted'] = eight_hours_ago.strftime(
        '%Y-%m-%d %H:%M:%S.%f') + '000'
    return self.m.depot_tools_gerrit.test_api.get_one_change_response_data(
        change_number=123, patchset=1, **kwargs)

  def should_lfg(self, gerrit_changes: List[GerritChange]) -> bool:
    """Returns whether looks for green logic should be run."""
    with self.m.step.nest('check should look for green') as pres:
      # Don't perform extra checks if LFG is not enabled.
      if not self.m.looks_for_green.enable_looks_for_green:
        pres.step_text = 'Looks for green not enabled'
        return False
      # Only look for green in CQ.
      if not self.m.cv.active:
        pres.step_text = 'Skipping looks for green outside of CQ'
        return False
      disallow = self.found_disallow_lfg_footer(gerrit_changes)
      if disallow:
        self._stats.status = LooksForGreenStatus.STATUS_SKIPPED_DISALLOW
        pres.step_text = 'Skipping looks for green due to disallow footer'
        self.set_stats()
        return False
      depended_cls = self.m.lfg_util.get_depended_cls(gerrit_changes)
      if depended_cls and not self.m.lfg_util.latest_submission_time(
          depended_cls, step_test_data=self._test_submission_data):
        # A CQ shouldn't be launched if any of the depended CLs are not included
        # in the run and are not submitted.
        # This clause covers the case of gerritAPI crash.
        self._stats.status = LooksForGreenStatus.STATUS_FOUND_NONE
        pres.step_text = 'Skipping looks for green due to depended cl(s) not being submitted'
        self.set_stats()
        return False
      self.set_stats()

    return True

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=1))
  def _get_snapshots(
      self,
      limit: Optional[int] = None,
      latest_start: Optional[timestamp_pb2.Timestamp] = None,
      bucket: Optional[str] = None,
      builder: Optional[str] = None,
      lookback_hours: Optional[float] = None,
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
      lookback_hours: The amount of time to lookback for a green snapshot.
          If None, defaults to self.lookback_hours.

    Returns:
      Snapshot builds found within the lookback period.
    """
    fields = frozenset({
        'id', 'input.gitiles_commit.id', 'output.properties', 'start_time',
        'end_time', 'status'
    })
    lookback_hours = lookback_hours or self.lookback_hours
    # Look back from latest_start if specified, otherwise from current time.
    if latest_start:
      latest_seconds = latest_start.ToSeconds()
      predicate = builds_service_pb2.BuildPredicate(
          create_time=common_pb2.TimeRange(
              start_time=timestamp_pb2.Timestamp(
                  seconds=latest_seconds - int(lookback_hours * 60 * 60),
              ), end_time=latest_start))
    else:
      latest_seconds = self.seconds_utc
      predicate = builds_service_pb2.BuildPredicate(
          create_time=common_pb2.TimeRange(
              start_time=timestamp_pb2.Timestamp(
                  seconds=latest_seconds - int(lookback_hours * 60 * 60),
              )))
    predicate.builder.project = self.m.buildbucket.build.builder.project
    predicate.builder.bucket = bucket or self._greenness_bucket
    predicate.builder.builder = builder or self._greenness_builder
    return self.m.buildbucket.search(predicate, limit=limit, fields=fields,
                                     timeout=60)

  def _parse_snapshot_result(
      self, snapshot_result: build_pb2.Build,
      requested_builders: Optional[List[str]] = None) -> Snapshot:
    """Parse buildbucket return into Snapshot."""
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

    if requested_builders:
      missing_builders = []
      running_greenness = 0
      for b in requested_builders:
        if b not in builder_greenness:
          missing_builders.append(b)
          continue
        running_greenness += builder_greenness[b].build_metric
      requested_builders_agg_green = int(running_greenness /
                                         len(requested_builders))
    else:
      requested_builders_agg_green = agg_green
      missing_builders = None

    approx_snap_age_hours = self.calc_approx_snap_age_hours(start_time)
    return Snapshot(
        bbid=snapshot_result.id,
        commit_sha=snapshot_result.input.gitiles_commit.id,
        start_time=start_time,
        end_time=end_time,
        agg_green=agg_green,
        requested_builders_agg_green=requested_builders_agg_green,
        requested_builders=requested_builders,
        requested_builders_missing_from_snapshot=missing_builders,
        approx_snap_age_hours=approx_snap_age_hours,
        builder_greenness=builder_greenness,
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
    if snapshot_stats.requested_builders:
      stats.requested_builders_greenness = snapshot_stats.requested_builders_agg_green
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
    greenness yet, so look back at the most recent snapshot-orchestrator
    that does have greenness populated.

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
      results = self._get_snapshots(bucket=bucket, builder=builder)
      scored_snapshot = self._get_latest_scored_snapshot(results)
      if not scored_snapshot:
        presentation.logs['latest scored snapshot greenness'] = (
            'found no scored snapshot in the latest builds')
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
        filter(
            lambda d: d.requested_builders_agg_green >= self.
            _greenness_threshold, parsed_results))
    if not green_results:
      return None
    max_greenness = max(
        [r.requested_builders_agg_green for r in parsed_results])
    greenest_results = list(
        filter(lambda d: d.requested_builders_agg_green == max_greenness,
               green_results))
    latest_snap = max(greenest_results, key=lambda k: k.start_time)
    return latest_snap

  def find_green_snapshot(
      self,
      latest_start: Optional[timestamp_pb2.Timestamp] = None,
      bucket: Optional[str] = None,
      builder: Optional[str] = None,
      requested_snapshot_builders: Optional[List[str]] = None,
      lookback_hours: Optional[float] = None,
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
      requested_snapshot_builders: Optional, a list of builders to consider when
        aggregating greenness.
      lookback_hours: Optional, the amount of time to lookback for a green
        snapshot.
    Returns:
      A green snapshot, if one was found.
    """
    with self.m.step.nest('find green snapshot') as presentation:
      results = self._get_snapshots(latest_start=latest_start, bucket=bucket,
                                    builder=builder,
                                    lookback_hours=lookback_hours)
      parsed_results = []
      for result in results:
        parsed_results.append(
            self._parse_snapshot_result(result, requested_snapshot_builders))
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
            f'{self.lookback_hours} hours.')
        self._stats.status = LooksForGreenStatus.STATUS_FOUND_NONE
        self.m.easy.set_properties_step(looks_for_green=self.stats)
      return green

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
          gerrit_changes, self.DISALLOW_LOOKS_FOR_GREEN_FOOTER,
          step_test_data=self.m.git_footers.test_api.step_test_data_factory(''))
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

  def resize_lfg_lookback(self, gerrit_changes: List[GerritChange],
                          builders_to_be_scheduled: List[str],
                          lookback_hours: Optional[float] = None) -> float:
    """Change LFG lookback based on the given parameters.

    Lookback can be resized based on depended changes and/or broken_until.

    Args:
      gerrit_changes: Gerrit changes to analyze.
      builders_to_be_scheduled: List of builders that need to be scheduled.
      lookback_hours: If specified, use the specified value when finding the
        minimum lookback hours. Only used by the auto-retrier.

    Returns:
      The resized lookback hours.
    """
    # Initialize to 2 weeks ago which should be a high enough value since we're
    # determining the minimum.
    hours_since_submission = 14 * 24
    with self.m.step.nest('resize depended cls') as pres:
      depended_cls = self.m.lfg_util.get_depended_cls(gerrit_changes)
      if depended_cls:
        submit_time = self.m.lfg_util.latest_submission_time(
            depended_cls, step_test_data=self._test_submission_data)
        if submit_time:
          hours_since_submission = (self.m.time.utcnow() -
                                    submit_time).total_seconds() / (60 * 60)
        pres.logs['depended_cls'] = (
          'One of the depended CLs was submitted ' + \
          f'{hours_since_submission:.2f} hours ago.'
        )

    global_hours_since_breakage = 7 * 24
    with self.m.step.nest('resize broken until') as pres:
      log = []
      for builder in builders_to_be_scheduled:
        config = self.m.cros_infra_config.get_builder_config(builder)
        broken_until_snapshot = config.general.broken_until
        if broken_until_snapshot:
          hours_since_breakage = self.m.cros_history.hours_since_breakage(
              broken_until_snapshot)
          if hours_since_breakage:
            log.append(
                f'{builder} was broken till {hours_since_breakage} hours ago.')
            global_hours_since_breakage = min(global_hours_since_breakage,
                                              hours_since_breakage)
      pres.logs['broken_until'] = log

    with self.m.step.nest('resize LFG lookback window') as pres:
      self.lookback_hours = min(
          lookback_hours or self.lookback_hours,
          # Reduce by 1 hour to account for the creation of the next snapshot +
          # the annealing run.
          hours_since_submission - 1,
          # Reduce by 30 mins to account for creation of the next snapshot.
          global_hours_since_breakage - 0.5)
      pres.step_text = (
          f'LFG lookback window is now {self.lookback_hours} hours')

    return self.lookback_hours
