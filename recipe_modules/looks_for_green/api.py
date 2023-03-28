# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple
import datetime
from typing import Any, List, Optional

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenProperties
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStats
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStatus

from google.protobuf import timestamp_pb2

from recipe_engine import recipe_api

Snapshot = namedtuple('Snapshot', [
    'bbid',
    'commit_sha',
    'start_time',
    'end_time',
    'agg_green',
    'approx_snap_age_hours',
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
    self.dry_run = properties.dry_run
    self._lookback_hours = properties.lookback_hours or 10
    self._greenness_threshold = properties.greenness_threshold or 80
    self.use_complete_snapshot = properties.use_complete_snapshot
    self._stats = LooksForGreenStats()
    self._now = None

  @property
  def now_utc(self) -> datetime.datetime:
    '''Returns the current UTC time.

    Initialized once and used throughout for any time calculations. Zero out
    the microseconds to use seconds as level of precision.
    '''
    if not self._now:
      self._now = self.m.time.utcnow().replace(microsecond=0)
    return self._now

  @property
  def _greenness_bucket(self) -> str:
    '''Returns bucket to query for greenness.
    '''
    return 'staging' if self.m.cros_infra_config.is_staging else 'postsubmit'

  @property
  def _greenness_builder(self) -> str:
    '''Returns builder to query for greenness.
    '''
    prefix = 'staging-' if self.m.cros_infra_config.is_staging else ''
    return f'{prefix}snapshot-orchestrator'

  def _get_snapshots(self,
                     limit: Optional[int] = None) -> List[build_pb2.Build]:
    '''Get snapshot builds within the lookback period.

    Optionally specify a limit of builds to return.
    '''
    fields = frozenset({
        'id', 'input.gitiles_commit.id', 'output.properties', 'start_time',
        'end_time', 'status'
    })
    # TODO(b/269180630): Remove ended_mask when build greenness is populated.
    # We can check greenness of snapshot-orchestrators that are still
    # in-progress as long as build greenness is populated.
    predicate = builds_service_pb2.BuildPredicate(
        create_time=common_pb2.TimeRange(
            start_time=timestamp_pb2.Timestamp(
                seconds=self.m.buildbucket.build.create_time.ToSeconds() -
                self._lookback_hours * 60 * 60,
            )), status=common_pb2.ENDED_MASK)
    predicate.builder.project = self.m.buildbucket.build.builder.project
    predicate.builder.bucket = self._greenness_bucket
    predicate.builder.builder = self._greenness_builder
    return self.m.buildbucket.search([predicate], limit=limit, fields=fields)

  def _parse_snapshot_result(self,
                             snapshot_result: build_pb2.Build) -> Snapshot:
    '''Parse buildbucket return into Snapshot NamedTuple.
    '''
    start_time = datetime.datetime.utcfromtimestamp(
        snapshot_result.start_time.seconds)
    end_time = datetime.datetime.utcfromtimestamp(
        snapshot_result.end_time.seconds)
    out_props = snapshot_result.output.properties
    try:
      agg_green = int(out_props['greenness']['aggregateMetric'])
    except ValueError:
      agg_green = -1
    approx_snap_age_hours = self.calc_approx_snap_age_hours(start_time)
    return Snapshot(bbid=snapshot_result.id,
                    commit_sha=snapshot_result.input.gitiles_commit.id,
                    start_time=start_time, end_time=end_time,
                    agg_green=agg_green,
                    approx_snap_age_hours=approx_snap_age_hours)

  def _set_snapshot_stats(
      self,
      snapshot_stats: Snapshot,
      suggested: bool = False,
  ) -> None:
    '''Set output stats using LooksForGreenStats proto fields.

    When suggested is True, populate stats for the snapshot that CQ Looks
    recommends to use. Otherwise, populate state for the latest snapshot that
    has go/greenness properties set.
    '''
    if not suggested:
      stats = self._stats.latest_scored
    else:
      stats = self._stats.suggested

    stats.snap_orch_greenness = snapshot_stats.agg_green
    stats.approx_snap_age_hours = snapshot_stats.approx_snap_age_hours
    stats.snap_orch_bbid = snapshot_stats.bbid
    stats.snap_commit_sha = snapshot_stats.commit_sha

  def get_latest_snapshot_greenness(self) -> int:
    '''Returns aggregate greenness of latest scored snapshot-orchestrator.

    Use common_pb2.ENDED_MASK to identify completed builds and limits return to
    1 build to get the latest scored build.

    Returns:
      aggregate greenness for latest scored snapshot-orchestrator, or -1 if
      not found.
    '''
    with self.m.step.nest(
        'checking latest scored snapshot greenness') as presentation:
      result = self._get_snapshots(limit=1)
      if result:
        snapshot_stats = self._parse_snapshot_result(result[0])
        presentation.logs['latest scored snapshot greenness'] = (
            f'latest scored snapshot-orchestrator '
            f'go/bbid/{snapshot_stats.bbid} has aggregate greenness of {snapshot_stats.agg_green}. '
            f'Start time: {snapshot_stats.start_time} End time: {snapshot_stats.end_time}'
            f'. The current time is {self.now_utc}')
        self._set_snapshot_stats(snapshot_stats)
      else:
        presentation.logs[
            'latest scored snapshot greenness'] = 'found no builds'
        return -1
      return snapshot_stats.agg_green

  def calc_approx_snap_age_hours(self,
                                 orch_start_time: datetime.datetime) -> int:
    '''Returns how many hours age the latest scored snap-orch started.

    This is used as an approximation of snapshot manifest age since a
    snapshot-orchestrator run starts within ~30 minutes of snapshot creation.

    Returns:
      Approx age in hours of snapshot used by latest scored snap-orch.
    '''
    delta = self.now_utc - orch_start_time
    days, seconds = delta.days, delta.seconds
    approx_snap_age_hours = days * 24 + seconds / 3600
    return round(approx_snap_age_hours)

  def _get_latest_green_snapshot(self, parsed_results: List[Snapshot]
                                ) -> Optional[Snapshot]:
    '''Get the latest green snapshot from a list of buildbucket snapshots.

    Return None if no green snapshot exists.
    '''
    green_results = list(
        filter(lambda d: d.agg_green >= self._greenness_threshold,
               parsed_results))
    if not green_results:
      return None
    latest_snap = max(green_results, key=lambda k: k.start_time)
    return latest_snap

  def find_green_snapshot(self) -> Optional[Snapshot]:
    '''Find a green snapshot within the lookback period if one exists.'''
    with self.m.step.nest('find green snapshot') as presentation:
      results = self._get_snapshots()
      parsed_results = []
      for result in results:
        parsed_results.append(self._parse_snapshot_result(result))
      green = self._get_latest_green_snapshot(parsed_results)
      if green:
        presentation.logs[
            'latest green'] = f'Found green snapshot: {green.commit_sha} with greenness {green.agg_green} and {green.approx_snap_age_hours} hours old.'
        self._set_snapshot_stats(green, suggested=True)
        self._stats.status = LooksForGreenStatus.STATUS_RAN_OLDER if not self.dry_run else LooksForGreenStatus.STATUS_RAN_LATEST_MINTED
        self.m.easy.set_properties_step(looks_for_green=self._stats)
      else:
        presentation.logs[
            'latest green'] = f'Found no snapshot of at least {self._greenness_threshold} greenness within the last {self._lookback_hours} hours.'
        self._stats.status = LooksForGreenStatus.STATUS_FOUND_NONE
        self.m.easy.set_properties_step(looks_for_green=self._stats)
      return green

  def is_snap_orch_green(self) -> bool:
    '''Returns whether the latest scored snapshot-orchestrator greenness is

    higher than greenness threshold.

    Returns:
      Whether latest scored snap-orch run is green
    '''
    self.latest_greenness = self.get_latest_snapshot_greenness()
    is_snap_orch_green = self.latest_greenness >= self._greenness_threshold
    self._stats.latest_scored.is_snap_orch_green = is_snap_orch_green
    # This logic is a bit brittle as it assumes that the caller is not going to
    # turn around and choose a different snapshot.
    if is_snap_orch_green or self.dry_run:
      self._stats.status = LooksForGreenStatus.STATUS_RAN_LATEST_MINTED
    self.m.easy.set_properties_step(looks_for_green=self._stats)
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
          f'{git_footers}')
      for git_footer in git_footers:
        if git_footer.lower() != 'false':
          found_disallow = True
          presentation.step_text = (
              f'Found {self.DISALLOW_LOOKS_FOR_GREEN_FOOTER}. Disabling looks '
              f'for green behavior.')

      return found_disallow
