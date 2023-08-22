# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import OrderedDict
from typing import Dict, Optional

from google.protobuf import struct_pb2

from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from recipe_engine import recipe_api
from recipe_engine.engine_types import StepPresentation

DEMAND_STATUSES = [common_pb2.SCHEDULED, common_pb2.STARTED]


class BuildbucketStatsApi(recipe_api.RecipeApi):
  """A module to get statistics from buildbucket."""

  def initialize(self) -> None:
    self._project = 'chromeos'
    self._snapshot_bucket = 'staging' if self.m.cros_infra_config.is_staging else 'postsubmit'
    self._snapshot_builder = 'staging-snapshot-orchestrator' if self.m.cros_infra_config.is_staging else 'snapshot-orchestrator'

  def get_build_count(self, bucket: str, status: common_pb2.Status) -> int:
    """Return the number of builds in the bucket with a specific status.

    Args:
      bucket: Buildbucket Bucket to search on.
      status: The status of builds to search for.

    Returns:
      The number of builds in the given bucket with given status.
    """
    builder = builder_common_pb2.BuilderID(
        project=self.m.buildbucket.build.builder.project, bucket=bucket)
    build_predicate = builds_service_pb2.BuildPredicate(builder=builder,
                                                        status=status)
    # Use a very small fields set to reduce the load on Buildbucket.
    return len(
        self.m.buildbucket.search(build_predicate, fields=('id',), limit=10000))

  def get_bucket_status(self, bucket: str) -> Dict[str, int]:
    """Return the number of builds in the bucket and their statuses.

    Args:
      bucket (str): Buildbucket bucket.

    Returns:
      Map of status to number of builds with that status in the bucket.
    """
    return {
        common_pb2.Status.Name(status): self.get_build_count(bucket, status)
        for status in DEMAND_STATUSES
    }

  @staticmethod
  def get_bot_demand(status_map: Dict[str, int]) -> int:
    """Return the demand for bots in a bot group.

    Args:
      status_map: Map of Buildbucket status to count.

    Returns:
      The current demand for bots in the group.
    """
    return sum([
        status_map[common_pb2.Status.Name(status)] for status in DEMAND_STATUSES
    ])

  def _get_snapshot_greenness(self, commit: str,
                              predicate: builds_service_pb2.BuildPredicate,
                              fields: frozenset,
                              pres: StepPresentation) -> OrderedDict():
    """Returns snapshot run for specified commit, if found.

    Retries bb query every half hour for up to 5 hours if we don't find the
    snapshot or build greenness is not yet set.
    """
    # Up to 10 30-minutes sleeps for a total wait of up to 5 hours.
    for _ in range(10):
      # Requesting 10 builds as that is more than enough. The default limit of 1000
      # crashes recipes. b/293312317
      results = self.m.buildbucket.search([predicate], limit=10, fields=fields,
                                          timeout=60)
      for result in results:
        if result.input.gitiles_commit.id == commit:
          # Ensure build greenness in last snapshot run is complete.
          output_props = result.output.properties
          if 'greenness' in output_props.fields and 'targetGreenness' in output_props[
              'greenness'].fields:
            snapshot_greenness = OrderedDict(
                self.reformat_target_dict(
                    output_props['greenness']['targetGreenness']))
            # Remove metric, since we only wait for build to finish, not tests.
            for v in snapshot_greenness.values():
              if 'metric' in v:
                del v['metric']
            pres.logs[
                'found'] = f'Found greenness for snapshot for commit {commit}: {snapshot_greenness}'
            return snapshot_greenness
      # Wait 30 mins and check again for snapshot with build greennness.
      self.m.step.empty('sleeping 30 minutes before checking again')
      self.m.time.sleep(30 * 60)
    pres.logs[
        'timed out'] = f'Timed out trying to find greenness for snapshot for commit {commit}.'
    return OrderedDict()

  def get_snapshot_greenness(self, commit: str, pres: StepPresentation,
                             end_bbid: Optional[int] = None) -> OrderedDict():
    """Returns snapshot run for specified commit, if found.

    If end_bbid is specified, return all runs that are older than the specified
    bbid (inclusive).
    """
    pres.logs[
        'looking'] = f'Trying to find greenness for snapshot for commit {commit}...'
    fields = frozenset(
        {'id', 'status', 'input.gitiles_commit.id', 'output.properties'})
    build_range = None
    if end_bbid:
      build_range = builds_service_pb2.BuildRange(end_build_id=end_bbid)
    predicate = builds_service_pb2.BuildPredicate(build=build_range)
    predicate.builder.project = self._project
    predicate.builder.bucket = self._snapshot_bucket
    predicate.builder.builder = self._snapshot_builder
    return self._get_snapshot_greenness(commit, predicate, fields, pres)

  def reformat_target_dict(
      self, list_value: struct_pb2.ListValue) -> Dict[str, Dict[str, str]]:
    '''Reformat ListValue to a dictionary, using target as key.

    This makes buildbucket properties like targetGreenness easier to work with.
    '''
    target_dict = {}
    for target in list_value:
      # Use build target as key.
      if 'target' in target:
        build_target = target['target']
        target_dict[build_target] = {}
        # Add other values.
        for k, v in target.items():
          if k != 'target':
            target_dict[build_target][k] = v
    return target_dict
