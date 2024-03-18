# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A collection of functions that poll Buildbucket for stats and output properties."""

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

from RECIPE_MODULES.chromeos.greenness.api import GreennessTuple

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

  def parse_local_greenness(self, properties: struct_pb2.Struct) -> OrderedDict:
    """Parse the local_greenness output properties.

    Args:
      properties: Output properties from a build containing a 'local_greenness'
        output property. This property should contain a 'greenness' key, which
        is a dict from builder name to GreennessTuple. If this property isn't
        set, an empty dict is returned.

    Returns:
      An OrderedDict mapping from builder name to GreennessTuple. If the
        local_greenness output property isn't found, the dict is empty.
    """
    snapshot_greenness = OrderedDict()

    if 'local_greenness' in properties.fields and 'greenness' in properties[
        'local_greenness'].fields:
      for builder, greenness_tuple in properties['local_greenness'][
          'greenness'].items():
        snapshot_greenness[builder] = GreennessTuple(*greenness_tuple.items())

    return snapshot_greenness

  def _poll_and_get_greenness(
      self,
      predicate: builds_service_pb2.BuildPredicate,
      retries: int,
      use_local_greenness: bool,
  ) -> OrderedDict:
    """Returns greenness for the specified build, if found.

    Predicate should be constructed to specify exactly one build that has a
    greenness output property, e.g. a snapshot orchestrator with a specific
    buildset.

    Retries bb query every half hour for up to retries times if we don't find
    the snapshot or build greenness is not yet set.

    Args:
      predicate: A predicate specifying a build that has a greenness output
        property. Usually this means the predicate specifies a snapshot
        orchestrator with a specific buildset tag.
      retries: Number of times to retry the query. There is a 30 minute sleep
        before each retry. This allows polling until the specified orchestrator
        publishes greenness.
      use_local_greenness: If true, parse the 'local_greenness' output property
        instead of the 'greenness' output property.

    Returns:
      An ordered dict mapping builder -> Greenness message as a dict. If
        use_local_greenness is true, the values are the Greenness tuple defined in
        greenness/api.py instead of the Greenness message. Dict will be empty if
        no greenness is found.
    """
    # Up to retries 30-minutes sleeps.
    # TODO(b/304548989): Use build_poller instead of sleeping.
    for i in range(retries + 1):
      results = self.m.buildbucket.search([predicate], limit=1,
                                          fields={'output.properties'},
                                          timeout=60)
      if results:
        result = results[0]
        # Ensure build greenness in last snapshot run is complete.
        output_props = result.output.properties
        if use_local_greenness:
          snapshot_greenness = self.parse_local_greenness(output_props)
          if snapshot_greenness:
            return snapshot_greenness
        elif 'greenness' in output_props.fields and 'builderGreenness' in output_props[
            'greenness'].fields:
          snapshot_greenness = OrderedDict(
              self.reformat_greenness_dict(
                  output_props['greenness']['builderGreenness']))

          return snapshot_greenness

      if i < retries:
        # Wait 30 mins and check again for snapshot with build greennness.
        self.m.step.empty('sleeping 30 minutes before checking again')
        self.m.time.sleep(30 * 60)

    return OrderedDict()

  def get_snapshot_greenness(
      self,
      commit: str,
      pres: StepPresentation,
      bucket: Optional[str] = None,
      builder: Optional[str] = None,
      end_bbid: Optional[int] = None,
      retries: int = 9,
      use_local_greenness: bool = False,
      wait_for_complete: bool = False,
  ) -> OrderedDict:
    """Returns greeneness for the specified commit, if found.

    Note this function may poll for up to retries * 30 minutes waiting for the
    specified greenness to be published.

    Args:
      commit: Commit to search for greenness for. Must be in
        chrome-internal.googlesource.com/chromeos/manifest-internal. The builder
        publishing greenness must have a buildset tag with this commit.
      pres: StepPresentation to write logs, etc. to.
      bucket: If specified, the bucket to search in. Defaults to
        self._snapshot_bucket.
      builder: If specified, the builder to search for. Defaults to
        self._snapshot_builder.
      end_bbid: If specified, return all runs that are older than the specified
        bbid (inclusive).
      retries: Number of times to retry the query. There is a 30 minute sleep
        before each retry. This allows polling until the specified orchestrator
        publishes greenness.
      use_local_greenness: If true, parse the 'local_greenness' output property
        instead of the 'greenness' output property.
      wait_for_complete: If true, wait until the build is completed. Otherwise,
        wait until the build publishes the build greenness output property. Note
        that the build will publish the build greenness before the test
        greenness; i.e. this should be set true if test greenness is required.

    Returns:
      An ordered dict mapping builder -> Greenness message as a dict. If
        use_local_greenness is true, the values are the Greenness tuple defined in
        greenness/api.py instead of the Greenness message. Dict will be empty if
        no greenness is found.
    """
    pres.logs[
        'looking'] = f'Trying to find greenness for snapshot for commit {commit}...'
    build_range = None
    if end_bbid:
      build_range = builds_service_pb2.BuildRange(end_build_id=end_bbid)
    predicate = builds_service_pb2.BuildPredicate(
        build=build_range,
        tags=self.m.buildbucket.tags(
            buildset=f'commit/gitiles/chrome-internal.googlesource.com/chromeos/manifest-internal/+/{commit}'
        ),
    )
    predicate.builder.project = self._project
    predicate.builder.bucket = bucket or self._snapshot_bucket
    predicate.builder.builder = builder or self._snapshot_builder
    if wait_for_complete:
      predicate.status = common_pb2.ENDED_MASK

    greenness = self._poll_and_get_greenness(predicate, retries,
                                             use_local_greenness)

    if greenness:
      pres.logs[
          'found'] = f'Found greenness for snapshot for commit {commit}: {greenness}'
    else:
      pres.logs[
          'timed out'] = f'Timed out trying to find greenness for snapshot for commit {commit}.'

    return greenness

  def reformat_greenness_dict(
      self, list_value: struct_pb2.ListValue) -> Dict[str, Dict[str, str]]:
    """Reformat ListValue to a dictionary, using builder as key.

    This makes buildbucket properties like builderGreenness easier to work with.
    """
    greenness_dict = {}
    for builder_dict in list_value:
      # Use builder as key.
      if 'builder' in builder_dict:
        builder = builder_dict['builder']
        greenness_dict[builder] = {}
        # Add other values.
        for k, v in builder_dict.items():
          if k != 'builder':
            greenness_dict[builder][k] = v
    return greenness_dict
