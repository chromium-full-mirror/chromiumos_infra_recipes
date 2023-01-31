# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime

from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStats

from google.protobuf import timestamp_pb2

from recipe_engine import recipe_api


class LooksForGreenApi(recipe_api.RecipeApi):
  """A module to look for green snapshots."""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._enable_looks_for_green = properties.enable_looks_for_green
    self._dry_run = properties.dry_run
    self._lookback_hours = properties.lookback_hours or 10
    self._greenness_threshold = properties.greenness_threshold or 80
    self._stats = LooksForGreenStats()
    self._now = None

  @property
  def now_utc(self):
    '''Returns the current UTC time.

    Initialized once and used throughout for any time calculations. Zero out
    the microseconds to use seconds as level of precision.

    Returns:
      (datetime.datetime) current UTC time
    '''
    if not self._now:
      self._now = self.m.time.utcnow().replace(microsecond=0)
    return self._now

  def get_latest_snapshot_greenness(self):
    '''Returns aggregate greenness of latest complete snapshot-orchestrator.

    Use common_pb2.ENDED_MASK to identify completed builds and limits return to
    1 build to get the latest build.

    Returns:
      agg_green (int): for latest snapshot-orchestrator, or -1 if not found.
    '''
    with self.m.step.nest('checking latest snapshot greenness') as presentation:
      fields = frozenset({
          'id', 'input.gitiles_commit.id', 'output.properties', 'start_time',
          'end_time', 'status'
      })
      predicate = builds_service_pb2.BuildPredicate(
          create_time=common_pb2.TimeRange(
              start_time=timestamp_pb2.Timestamp(
                  seconds=self.m.buildbucket.build.create_time.ToSeconds() -
                  self._lookback_hours * 60 * 60,
              )), status=common_pb2.ENDED_MASK)
      predicate.builder.project = self.m.buildbucket.build.builder.project
      predicate.builder.bucket = 'postsubmit'
      predicate.builder.builder = 'snapshot-orchestrator'
      result = self.m.buildbucket.search([predicate], limit=1, fields=fields)
      if result:
        snap_orch_bbid = result[0].id
        snap_commit_sha = result[0].input.gitiles_commit.id
        snap_orch_start_time = datetime.datetime.utcfromtimestamp(
            result[0].start_time.seconds)
        snap_orch_end_time = datetime.datetime.utcfromtimestamp(
            result[0].end_time.seconds)
        out_props = result[0].output.properties
        try:
          agg_green = int(out_props['greenness']['aggregateMetric'])
        except ValueError:
          agg_green = -1
        presentation.logs['latest snapshot greenness'] = (
            f'latest snapshot-orchestrator '
            f'go/bbid/{snap_orch_bbid} has aggregate greenness of {agg_green}. '
            f'Start time: {snap_orch_start_time} End time: {snap_orch_end_time}'
            f'. The current time is {self.now_utc}')
        approx_snap_age_hours = self.calc_approx_snap_age_hours(
            snap_orch_start_time)
        self._stats.snap_orch_greenness = agg_green
        self._stats.approx_snap_age_hours = approx_snap_age_hours
        self._stats.snap_orch_bbid = snap_orch_bbid
        self._stats.snap_commit_sha = snap_commit_sha
      else:
        presentation.logs['latest snapshot greenness'] = 'found no builds'
        agg_green = -1
      return agg_green

  def calc_approx_snap_age_hours(self, orch_start_time):
    '''Returns how many hours age the latest snap-orch started.

    This is used as an approximation of snapshot manifest age since a
    snapshot-orchestrator run starts within ~30 minutes of snapshot creation.

    Returns:
      (int) Approx age in hours of snapshot used by latest snap-orch.
    '''
    delta = self.now_utc - orch_start_time
    days, seconds = delta.days, delta.seconds
    approx_snap_age_hours = days * 24 + seconds / 3600
    return round(approx_snap_age_hours)

  def is_snap_orch_green(self):
    '''Returns whether the last snapshot-orchestrator greenness is higher than

    greenness threshold.

    Returns:
      (bool) Whether last snap-orch run is green
    '''
    self.latest_greenness = self.get_latest_snapshot_greenness()
    is_snap_orch_green = self.latest_greenness >= self._greenness_threshold
    self._stats.is_snap_orch_green = is_snap_orch_green
    self.m.easy.set_properties_step(looks_for_green=self._stats)
    return is_snap_orch_green
