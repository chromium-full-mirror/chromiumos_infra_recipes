# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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
    self._max_concurrent_snapshot_runs = properties.max_concurrent_snapshot_runs or 25
    self._lookback_hours = properties.lookback_hours or 10
    self._greenness_threshold = properties.greenness_threshold or 80
    self.use_complete_snapshot = properties.use_complete_snapshot
    self._stats = LooksForGreenStats()
    self._now = None
    self._should_lfg = None

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

  def _has_merge_commit(self, gerrit_changes: List[GerritChange]) -> bool:
    '''Returns whether gerrit_changes contains one or more merge commit.'''
    with self.m.context(cwd=self.m.cros_source.workspace_path):
      patch_sets = self.m.gerrit.fetch_patch_sets(gerrit_changes)
      for patch in patch_sets:
        project_paths = self.m.cros_source.find_project_paths(
            patch.project, patch.branch)
        for project_path in project_paths:
          with self.m.context(
              cwd=self.m.cros_source.workspace_path.join(project_path)):
            commit = self.m.git.fetch_ref(patch.git_fetch_url,
                                          patch.git_fetch_ref)
            # One merge commit in a group of CLs is enough to stop LFG.
            if self.m.git.is_merge_commit(commit):
              return True
      return False

  def should_lfg(self, exps: Dict[str, bool],
                 gerrit_changes: List[GerritChange]) -> bool:
    '''Returns whether looks for green logic should be run.'''
    if self._should_lfg is None:
      # This check shouldn't be fatal to a build.
      self._should_lfg = False
      with self.m.failures.ignore_exceptions():
        with self.m.step.nest('check should look for green') as pres:
          exp_enabled = "chromeos.cros_infra_config.cq_looks" in exps
          lfg_enabled = self.m.looks_for_green.enable_looks_for_green
          # Don't perform extra checks if we don't meet these preconditions.
          if not exp_enabled or not lfg_enabled:
            self._should_lfg = False
            return self._should_lfg
          # Only look for green in CQ.
          if not self.m.cq.active:
            pres.step_text = 'Skipping looks for green outside of CQ'
            self._should_lfg = False
            return self._should_lfg
          disallow = self.found_disallow_lfg_footer(gerrit_changes)
          has_merge_commit = self._has_merge_commit(gerrit_changes)
          self._should_lfg = (
              exp_enabled and lfg_enabled and not disallow and
              not has_merge_commit)
          should_lfg_log = (
              f'Found CQ looks experiment: {exp_enabled}, Found LFG enabled:'
              f' {lfg_enabled}, Found disallow footer: {disallow}, Found has'
              f' merge commit {has_merge_commit}')
          # TODO(b/276363760): Don't LFG with Cq-Depend until supported.
          if self._should_lfg:
            with self.m.step.nest('check if CL uses Cq-Depend'):
              if self.m.git_footers.get_footer_values(gerrit_changes,
                                                      'Cq-Depend'):
                self._should_lfg = False
                should_lfg_log += '. Found Cq-Depend footer'
                pres.logs['Cq-Depend footer'] = (
                    'Found Cq-Depend footer. Skipping'
                    ' looks for green.')
          if not self._should_lfg:
            should_lfg_log += '. Using original snapshot.'
          pres.logs['should_lfg'] = should_lfg_log
    return self._should_lfg

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=1))
  def _get_snapshots(self,
                     limit: Optional[int] = None) -> List[build_pb2.Build]:
    '''Get snapshot builds within the lookback period.

    Optionally specify a limit of builds to return.
    '''
    fields = frozenset({
        'id', 'input.gitiles_commit.id', 'output.properties', 'start_time',
        'end_time', 'status'
    })
    predicate = builds_service_pb2.BuildPredicate(
        create_time=common_pb2.TimeRange(
            start_time=timestamp_pb2.Timestamp(
                seconds=self.m.buildbucket.build.create_time.ToSeconds() -
                self._lookback_hours * 60 * 60,
            )))
    predicate.builder.project = self.m.buildbucket.build.builder.project
    predicate.builder.bucket = self._greenness_bucket
    predicate.builder.builder = self._greenness_builder
    return self.m.buildbucket.search([predicate], limit=limit, fields=fields,
                                     timeout=60)

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

  def _get_latest_scored_snapshot(
      self, build_results: List[build_pb2.Build]) -> Optional[build_pb2.Build]:
    '''Find the latest snapshot with a greenness score.'''
    for build in build_results:
      if 'greenness' in build.output.properties and \
      'aggregateMetric' in build.output.properties['greenness']:
        return build
    return None

  def get_latest_snapshot_greenness(self) -> int:
    '''Returns aggregate greenness of latest scored snapshot-orchestrator.

    Or -1 if no latest scored snapshot is found.

    If the latest snapshot-orchestrator has just started, we won't have
    greenness yet, so look back at the most recent snapshot-orchestrator (of
    the self._max_concurrent_snapshot_runs most recent runs) that does have
    greenness populated.

    Returns:
      aggregate greenness for latest scored snapshot-orchestrator, or -1 if
      not found.
    '''
    with self.m.step.nest(
        'checking latest scored snapshot greenness') as presentation:
      results = self._get_snapshots(limit=self._max_concurrent_snapshot_runs)
      scored_snapshot = self._get_latest_scored_snapshot(results)
      if not scored_snapshot:
        presentation.logs['latest scored snapshot greenness'] = (
            'found no scored snapshot in the latest '
            f'{self._max_concurrent_snapshot_runs} builds')
        return -1
      snapshot_stats = self._parse_snapshot_result(scored_snapshot)
      presentation.logs['latest scored snapshot greenness'] = (
          'latest scored snapshot-orchestrator '
          f'go/bbid/{snapshot_stats.bbid} has aggregate greenness of '
          f'{snapshot_stats.agg_green}. Start time: {snapshot_stats.start_time}'
          f' End time: {snapshot_stats.end_time}. The current time is '
          f'{self.now_utc}')
      self._set_snapshot_stats(snapshot_stats)
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
        presentation.logs['latest green'] = (
            f'Found green snapshot: {green.commit_sha} with '
            f'greenness {green.agg_green} and {green.approx_snap_age_hours} '
            'hours old.')
        self._set_snapshot_stats(green, suggested=True)
        self._stats.status = LooksForGreenStatus.STATUS_RAN_OLDER if not self.dry_run else LooksForGreenStatus.STATUS_RAN_LATEST_MINTED
        self.m.easy.set_properties_step(looks_for_green=self._stats)
      else:
        presentation.logs['latest green'] = (
            'Found no snapshot of at least '
            f'{self._greenness_threshold} greenness within the last '
            f'{self._lookback_hours} hours.')
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
          f'{sorted(git_footers)}')
      for git_footer in git_footers:
        if git_footer.lower() != 'false':
          found_disallow = True
          presentation.step_text = (
              f'Found {self.DISALLOW_LOOKS_FOR_GREEN_FOOTER}. Disabling looks '
              'for green behavior.')

      return found_disallow
