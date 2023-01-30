# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

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

  def get_latest_snapshot_greenness(self):
    '''Returns aggregate greenness of latest complete snapshot-orchestrator.

    Use common_pb2.ENDED_MASK to identify completed builds and limits return to
    1 build to get the latest build.

    Returns:
      aggGreen (int): for latest snapshot-orchestrator, or -1 if not found.
    '''
    with self.m.step.nest('checking latest snapshot greenness') as presentation:
      fields = frozenset({'id', 'output.properties'})
      predicate = builds_service_pb2.BuildPredicate(
          create_time=common_pb2.TimeRange(
              start_time=timestamp_pb2.Timestamp(
                  seconds=self.m.buildbucket.build.create_time.ToSeconds() -
                  self._lookback_hours * 60 * 60,
              )), status=common_pb2.ENDED_MASK)
      predicate.builder.project = self.m.buildbucket.build.builder.project
      # TODO(b/211620738): Use staging builder for staging env.
      predicate.builder.bucket = 'postsubmit'
      predicate.builder.builder = 'snapshot-orchestrator'
      result = self.m.buildbucket.search([predicate], limit=1, fields=fields)
      if result:
        bbid = result[0].id
        out_props = result[0].output.properties
        try:
          aggGreen = int(out_props['greenness']['aggregateMetric'])
        except ValueError:
          aggGreen = -1
        presentation.logs[
            'latest snapshot greenness'] = f'latest snapshot-orchestrator go/bbid/{bbid} has aggregate greenness of {aggGreen}'
      else:
        presentation.logs['latest snapshot greenness'] = 'found no builds'
        aggGreen = -1
      return aggGreen

  def is_snap_orch_green(self):
    '''Returns whether the last snapshot-orchestrator greenness is higher than

    greenness threshold.

    Returns:
      (bool) Whether last snap-orch run is green
    '''
    latest_greenness = self.get_latest_snapshot_greenness()
    return latest_greenness >= self._greenness_threshold
