# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_history',
]


def RunSteps(api):
  expected = ['eve-snapshot', 'bob-snapshot']
  snapshot = common_pb2.GitilesCommit()
  result = api.cros_history.get_snapshot_builds(
      snapshot, ['eve-snapshot', 'winky-snapshot', 'bob-snapshot'],
      common_pb2.STATUS_UNSPECIFIED)
  result_builders = [build.builder.builder for build in result]
  api.assertions.assertEqual(result_builders, expected)


def GenTests(api):
  yield (api.test('basic') + api.buildbucket.simulated_search_results([
      build_pb2.Build(id=123,
                      builder=build_pb2.BuilderID(builder='eve-snapshot')),
      build_pb2.Build(id=231,
                      builder=build_pb2.BuilderID(builder='bob-snapshot')),
      build_pb2.Build(id=312,
                      builder=build_pb2.BuilderID(builder='cq-orchestrator')),
  ], 'get snapshot builds.buildbucket.search'))
