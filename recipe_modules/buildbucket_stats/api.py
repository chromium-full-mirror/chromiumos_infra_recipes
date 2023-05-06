# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Dict

from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from recipe_engine import recipe_api

DEMAND_STATUSES = [common_pb2.SCHEDULED, common_pb2.STARTED]


class BuildbucketStatsApi(recipe_api.RecipeApi):
  """A module to get statistics from buildbucket."""

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
