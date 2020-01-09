# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2

from recipe_engine import recipe_api

DEMAND_STATUSES = [common_pb2.SCHEDULED, common_pb2.STARTED]


class BuildbucketStatsApi(recipe_api.RecipeApi):
  """A module to get statistics from buildbucket."""

  def get_build_count(self, bucket, status):
    """Return the number of builds in the bucket with a specific status.

    Args:
      bucket (str): Buildbucket Bucket to search on.
      status (common_pb2.Status): The status of builds to search for.

    Returns:
      The number of builds (int) in the given bucket with given status.
    """
    builder = build_pb2.BuilderID(
        project=self.m.buildbucket.build.builder.project, bucket=bucket)
    build_predicate = rpc_pb2.BuildPredicate(builder=builder, status=status)
    # Use a very small fields set to reduce the load on Buildbucket.
    return len(
        self.m.buildbucket.search(build_predicate, fields=('id',), limit=10000))

  def get_bucket_status(self, bucket):
    """Return the number of builds in the bucket and their statuses.

    Args:
      bucket (str): Buildbucket bucket.

    Returns:
      Map (str->int) of status to number of builds with that status in the
      bucket.
    """
    return {
        common_pb2.Status.Name(status): self.get_build_count(bucket, status)
        for status in DEMAND_STATUSES
    }

  def get_bot_demand(self, status_map):
    """Return the demand for bots in a bot group.

    Args:
      status_map (str->int): Map of Buildbucket status to count.

    Returns:
      int, the current demand for bots in the group.
    """
    return sum([
        status_map[common_pb2.Status.Name(status)] for status in DEMAND_STATUSES
    ])
