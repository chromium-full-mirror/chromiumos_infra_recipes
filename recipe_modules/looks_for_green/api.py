# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import timestamp_pb2

from recipe_engine import recipe_api


class CqLooksApi(recipe_api.RecipeApi):
  """A module to look for green CQ snapshots."""

  def get_unfinished_or_failed_snapshot_ids(self, snapshot_ids):
    """Returns a set of unfinished or failed snapshot ids.

    Args:
      snapshot_ids (set): The set of snapshot ids to be used in build plan.

    Returns:
      A tuple of two sets:
        A set of snapshot ids referring to builds that are unfinished.
        A set of snapshot ids referring to builds that are failed.
    """
    with self.m.step.nest('unfinished or failed snapshots') as presentation:
      cqlooks_log = []
      fields = frozenset({'id', 'status', 'builder', 'tags', 'critical'})
      # TODO(b/211620738): Parameterize LOOKBACK_HOURS in config.
      LOOKBACK_HOURS = 14
      unfinished, failed = set(), set()
      build_predicates = []
      for sid in sorted(list(snapshot_ids)):
        predicate = builds_service_pb2.BuildPredicate(
            create_time=common_pb2.TimeRange(
                start_time=timestamp_pb2.Timestamp(
                    seconds=self.m.buildbucket.build.create_time.ToSeconds() -
                    LOOKBACK_HOURS * 60 * 60,
                )), tags=self.m.buildbucket.tags(snapshot=str(sid)))
        predicate.builder.project = self.m.buildbucket.build.builder.project
        predicate.builder.bucket = 'postsubmit'
        build_predicates.append(predicate)
      builds = self.m.buildbucket.search(build_predicates, fields=fields)
      # Filter out non-critical builds as we can't set this in BuildPredicate.
      # Filter out non-snapshot builds which use snapshot id as their buildspec.
      builds = [
          b for b in builds if b.critical == common_pb2.YES and
          b.builder.builder.endswith("-snapshot")
      ]

      # Format the build results for easier lookup by snapshot id.
      builds_by_snapshot_ids = {}
      for build in builds:
        for tag in build.tags:
          if tag.key == 'snapshot':
            try:
              builds_by_snapshot_ids[tag.value].append(build.status)
            except KeyError:
              builds_by_snapshot_ids[tag.value] = [build.status]

      for sid in sorted(list(snapshot_ids)):
        if sid in sorted(builds_by_snapshot_ids.keys()):
          builds = builds_by_snapshot_ids[sid]
          cqlooks_log.append(
              'For snapshot {} in the last {} hours, found {} build(s)'.format(
                  sid, LOOKBACK_HOURS, len(builds)))
          for build_status in builds:
            if build_status in [common_pb2.FAILURE, common_pb2.INFRA_FAILURE]:
              failed.add(sid)
            elif build_status in [
                common_pb2.SCHEDULED, common_pb2.STARTED,
                common_pb2.STATUS_UNSPECIFIED, common_pb2.CANCELED
            ]:
              unfinished.add(sid)
            else:
              cqlooks_log.append('Snapshot {} is green for build(s) {}'.format(
                  sid, builds))
        else:
          cqlooks_log.append(
              'For snapshot {} in the last {} hours, did not find any builds. Treating as unfinished.'
              .format(sid, LOOKBACK_HOURS))
          unfinished.add(sid)

      if unfinished or failed:
        cqlooks_log.append(
            "CQ looks: Found {} unfinished and {} failed snapshots.".format(
                len(unfinished), len(failed)))
      else:
        cqlooks_log.append("CQ looks: All snapshots green. Proceeding.")
      presentation.logs['unfinished or failed snapshots'] = cqlooks_log
      return unfinished, failed
